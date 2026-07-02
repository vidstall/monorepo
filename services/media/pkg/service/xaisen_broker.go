package service

import (
	"context"
	"crypto/ecdh"
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/livekit/livekit-server/pkg/config"
	"github.com/livekit/protocol/auth"
	"golang.org/x/crypto/blake2b"
	"golang.org/x/crypto/chacha20poly1305"
	"golang.org/x/crypto/hkdf"
)

const brokerSessionTTL = 30 * time.Minute

type brokerSession struct {
	key       []byte
	expiresAt time.Time
	counter   uint64
	routerID  string
}

type xaisenBroker struct {
	nodeID     string
	clusterID  string
	clientURL  string
	apiKey     string
	apiSecret  string
	privateKey *ecdh.PrivateKey
	sessions   map[string]*brokerSession
	mu         sync.Mutex
}

type sessionRequest struct {
	EphemeralPublicKey string `json:"ephemeralPublicKey"`
	IssuedAtMS         int64  `json:"issuedAtMs"`
	MediaNodeID        string `json:"mediaNodeId"`
	Nonce              string `json:"nonce"`
	RouterNodeID       string `json:"routerNodeId"`
	RouterPublicKey    string `json:"routerPublicKey"`
	Signature          string `json:"signature"`
}

type encryptedEnvelope struct {
	SessionID  string `json:"sessionId,omitempty"`
	Counter    string `json:"counter"`
	Ciphertext string `json:"ciphertext"`
	Tag        string `json:"tag"`
}

type tokenRequest struct {
	AssignmentRevision int    `json:"assignmentRevision"`
	Capacity           int    `json:"capacity"`
	Identity           string `json:"identity"`
	Metadata           string `json:"metadata"`
	RentalID           string `json:"rentalId"`
	RoomName           string `json:"roomName"`
}

// StartXaisenBroker exposes the off-chain pairing and token broker next to a
// LiveKit media node. The LiveKit signing secret never leaves this process.
func StartXaisenBroker(ctx context.Context, conf *config.Config, nodeID string) error {
	if os.Getenv("XAISEN_BROKER_DISABLED") == "true" {
		return nil
	}
	if configuredNodeID := os.Getenv("XAISEN_MEDIA_NODE_ID"); configuredNodeID != "" {
		nodeID = configuredNodeID
	}
	if len(conf.Keys) != 1 {
		return fmt.Errorf("Xaisen broker requires exactly one active LiveKit key")
	}
	var apiKey, secret string
	for apiKey, secret = range conf.Keys {
	}
	privateKey, err := loadOrCreateX25519Key(os.Getenv("XAISEN_MEDIA_KEY_PATH"))
	if err != nil {
		return err
	}
	b := &xaisenBroker{
		nodeID: nodeID, clusterID: os.Getenv("XAISEN_CLUSTER_ID"), clientURL: os.Getenv("XAISEN_LIVEKIT_URL"),
		apiKey: apiKey, apiSecret: secret, privateKey: privateKey, sessions: make(map[string]*brokerSession),
	}
	if b.clusterID == "" || b.clientURL == "" {
		return fmt.Errorf("XAISEN_CLUSTER_ID and XAISEN_LIVEKIT_URL are required")
	}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /xaisen/v1/health", b.health)
	mux.HandleFunc("POST /xaisen/v1/session", b.session)
	mux.HandleFunc("POST /xaisen/v1/token", b.token)
	server := &http.Server{Addr: envOr("XAISEN_BROKER_ADDR", ":7890"), Handler: mux, ReadHeaderTimeout: 5 * time.Second}
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdown)
	}()
	go func() {
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			fmt.Fprintf(os.Stderr, "xaisen broker stopped: %v\n", err)
		}
	}()
	return nil
}

func (b *xaisenBroker) health(w http.ResponseWriter, _ *http.Request) {
	publicKey := b.privateKey.PublicKey().Bytes()
	writeJSON(w, http.StatusOK, map[string]any{
		"ready": true, "nodeId": b.nodeID, "clusterId": b.clusterID,
		"timestampMs": time.Now().UnixMilli(), "x25519PublicKey": base64.StdEncoding.EncodeToString(publicKey),
	})
}

func (b *xaisenBroker) session(w http.ResponseWriter, r *http.Request) {
	var request sessionRequest
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 16<<10)).Decode(&request); err != nil {
		http.Error(w, "invalid session request", http.StatusBadRequest)
		return
	}
	if request.MediaNodeID != b.nodeID || abs(time.Now().UnixMilli()-request.IssuedAtMS) > 60_000 {
		http.Error(w, "stale or misdirected session request", http.StatusUnauthorized)
		return
	}
	publicKey, err := base64.StdEncoding.DecodeString(request.RouterPublicKey)
	if err != nil || len(publicKey) != ed25519.PublicKeySize {
		http.Error(w, "invalid router public key", http.StatusUnauthorized)
		return
	}
	signature, err := base64.StdEncoding.DecodeString(request.Signature)
	if err != nil || !ed25519.Verify(publicKey, canonicalSession(request), signature) {
		http.Error(w, "invalid router signature", http.StatusUnauthorized)
		return
	}
	if err := verifyRouterRole(r.Context(), request.RouterNodeID, publicKey); err != nil {
		http.Error(w, err.Error(), http.StatusUnauthorized)
		return
	}
	peerBytes, err := base64.StdEncoding.DecodeString(request.EphemeralPublicKey)
	if err != nil {
		http.Error(w, "invalid ephemeral key", http.StatusBadRequest)
		return
	}
	peer, err := ecdh.X25519().NewPublicKey(peerBytes)
	if err != nil {
		http.Error(w, "invalid ephemeral key", http.StatusBadRequest)
		return
	}
	shared, err := b.privateKey.ECDH(peer)
	if err != nil {
		http.Error(w, "key agreement failed", http.StatusBadRequest)
		return
	}
	sessionRandom := make([]byte, 24)
	_, _ = rand.Read(sessionRandom)
	sessionID := base64.RawURLEncoding.EncodeToString(sessionRandom)
	reader := hkdf.New(sha256.New, shared, []byte(sessionID), canonicalSession(request))
	key := make([]byte, chacha20poly1305.KeySize)
	if _, err := io.ReadFull(reader, key); err != nil {
		http.Error(w, "key derivation failed", http.StatusInternalServerError)
		return
	}
	expiresAt := time.Now().Add(brokerSessionTTL)
	b.mu.Lock()
	b.sessions[sessionID] = &brokerSession{key: key, expiresAt: expiresAt, routerID: request.RouterNodeID}
	b.mu.Unlock()
	writeJSON(w, http.StatusOK, map[string]any{"sessionId": sessionID, "expiresAtMs": expiresAt.UnixMilli()})
}

func (b *xaisenBroker) token(w http.ResponseWriter, r *http.Request) {
	var envelope encryptedEnvelope
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 64<<10)).Decode(&envelope); err != nil {
		http.Error(w, "invalid token envelope", http.StatusBadRequest)
		return
	}
	counter, err := strconv.ParseUint(envelope.Counter, 10, 64)
	if err != nil {
		http.Error(w, "invalid counter", http.StatusBadRequest)
		return
	}
	b.mu.Lock()
	session := b.sessions[envelope.SessionID]
	if session == nil || time.Now().After(session.expiresAt) || counter <= session.counter {
		b.mu.Unlock()
		http.Error(w, "expired session or replay", http.StatusUnauthorized)
		return
	}
	session.counter = counter
	b.mu.Unlock()
	plaintext, err := openEnvelope(session.key, envelope.SessionID, counter, envelope)
	if err != nil {
		http.Error(w, "invalid encrypted request", http.StatusUnauthorized)
		return
	}
	var request tokenRequest
	if err := json.Unmarshal(plaintext, &request); err != nil || request.RoomName == "" || request.Identity == "" {
		http.Error(w, "invalid token request", http.StatusBadRequest)
		return
	}
	if err := verifyAssignment(r.Context(), request.RentalID, request.AssignmentRevision, b.clusterID, session.routerID); err != nil {
		http.Error(w, err.Error(), http.StatusForbidden)
		return
	}
	grant := &auth.VideoGrant{RoomJoin: true, Room: request.RoomName}
	grant.SetCanPublish(true)
	grant.SetCanPublishData(true)
	grant.SetCanSubscribe(true)
	token, err := auth.NewAccessToken(b.apiKey, b.apiSecret).
		SetIdentity(request.Identity).SetMetadata(request.Metadata).SetValidFor(5 * time.Minute).
		SetVideoGrant(grant).ToJWT()
	if err != nil {
		http.Error(w, "token signing failed", http.StatusInternalServerError)
		return
	}
	responseCounter := counter + 1
	response, err := sealEnvelope(session.key, envelope.SessionID, responseCounter, map[string]string{
		"participantToken": token, "serverUrl": b.clientURL,
	})
	if err != nil {
		http.Error(w, "response encryption failed", http.StatusInternalServerError)
		return
	}
	writeJSON(w, http.StatusOK, response)
}

func canonicalSession(r sessionRequest) []byte {
	return []byte(fmt.Sprintf("ephemeralPublicKey=%s\nissuedAtMs=%d\nmediaNodeId=%s\nnonce=%s\nrouterNodeId=%s",
		r.EphemeralPublicKey, r.IssuedAtMS, r.MediaNodeID, r.Nonce, r.RouterNodeID))
}

func openEnvelope(key []byte, sessionID string, counter uint64, envelope encryptedEnvelope) ([]byte, error) {
	aead, err := chacha20poly1305.New(key)
	if err != nil {
		return nil, err
	}
	ciphertext, err := base64.StdEncoding.DecodeString(envelope.Ciphertext)
	if err != nil {
		return nil, err
	}
	tag, err := base64.StdEncoding.DecodeString(envelope.Tag)
	if err != nil {
		return nil, err
	}
	return aead.Open(nil, counterNonce(counter), append(ciphertext, tag...), []byte(sessionID))
}

func sealEnvelope(key []byte, sessionID string, counter uint64, value any) (encryptedEnvelope, error) {
	plaintext, err := json.Marshal(value)
	if err != nil {
		return encryptedEnvelope{}, err
	}
	aead, err := chacha20poly1305.New(key)
	if err != nil {
		return encryptedEnvelope{}, err
	}
	sealed := aead.Seal(nil, counterNonce(counter), plaintext, []byte(sessionID))
	cut := len(sealed) - chacha20poly1305.Overhead
	return encryptedEnvelope{Counter: strconv.FormatUint(counter, 10), Ciphertext: base64.StdEncoding.EncodeToString(sealed[:cut]), Tag: base64.StdEncoding.EncodeToString(sealed[cut:])}, nil
}

func counterNonce(counter uint64) []byte {
	nonce := make([]byte, chacha20poly1305.NonceSize)
	binary.BigEndian.PutUint64(nonce[4:], counter)
	return nonce
}

func loadOrCreateX25519Key(path string) (*ecdh.PrivateKey, error) {
	if path == "" {
		path = "/var/lib/xaisen/media-x25519.key"
	}
	if encoded, err := os.ReadFile(path); err == nil {
		raw, err := base64.RawStdEncoding.DecodeString(strings.TrimSpace(string(encoded)))
		if err != nil {
			return nil, err
		}
		return ecdh.X25519().NewPrivateKey(raw)
	}
	privateKey, err := ecdh.X25519().GenerateKey(rand.Reader)
	if err != nil {
		return nil, err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return nil, err
	}
	if err := os.WriteFile(path, []byte(base64.RawStdEncoding.EncodeToString(privateKey.Bytes())), 0o600); err != nil {
		return nil, err
	}
	return privateKey, nil
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

func envOr(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}

func abs(value int64) int64 {
	if value < 0 {
		return -value
	}
	return value
}

func verifyRouterRole(ctx context.Context, routerID string, publicKey []byte) error {
	if os.Getenv("SUI_RPC_URL") == "" || os.Getenv("CONTRACT_PACKAGE_ID") == "" {
		return fmt.Errorf("Sui router verification is not configured")
	}
	registered, err := queryMoveEvents(ctx, "WorkerRegistered")
	if err != nil {
		return err
	}
	digest := blake2b.Sum256(append([]byte{0}, publicKey...))
	expectedOwner := "0x" + fmt.Sprintf("%x", digest[:])
	foundOwner := false
	for _, event := range registered {
		if field(event, "node_id") == routerID && normalizeAddress(field(event, "owner")) == normalizeAddress(expectedOwner) {
			foundOwner = true
			break
		}
	}
	if !foundOwner {
		return fmt.Errorf("router key does not own the registered node")
	}
	roles, err := queryMoveEvents(ctx, "RoleAssigned")
	if err != nil {
		return err
	}
	for i := len(roles) - 1; i >= 0; i-- {
		if field(roles[i], "node_id") != routerID {
			continue
		}
		if field(roles[i], "role") == "2" {
			return nil
		}
		break
	}
	return fmt.Errorf("router does not have ROLE_ROUTER")
}

func verifyAssignment(ctx context.Context, rentalID string, revision int, clusterID, routerID string) error {
	if clusterID == "" || routerID == "" {
		return fmt.Errorf("invalid routed assignment")
	}
	if os.Getenv("SUI_RPC_URL") == "" || os.Getenv("CONTRACT_PACKAGE_ID") == "" {
		return fmt.Errorf("Sui assignment verification is not configured")
	}
	events, err := queryMoveEvents(ctx, "RoutedAssignmentUpdated")
	if err != nil {
		return err
	}
	for i := len(events) - 1; i >= 0; i-- {
		event := events[i]
		if field(event, "rental_id") != rentalID {
			continue
		}
		if field(event, "cluster_id") == clusterID && field(event, "router_node_id") == routerID && field(event, "revision") == strconv.Itoa(revision) {
			return nil
		}
		return fmt.Errorf("routed assignment is stale or targets another cluster")
	}
	return fmt.Errorf("routed assignment was not found")
}

type suiEventPage struct {
	Result struct {
		Data []struct {
			ParsedJSON map[string]any `json:"parsedJson"`
		} `json:"data"`
	} `json:"result"`
	Error any `json:"error"`
}

func queryMoveEvents(ctx context.Context, eventName string) ([]map[string]any, error) {
	payload := map[string]any{
		"jsonrpc": "2.0", "id": 1, "method": "suix_queryEvents",
		"params": []any{map[string]any{"MoveEventType": os.Getenv("CONTRACT_PACKAGE_ID") + "::node_registry::" + eventName}, nil, 1000, false},
	}
	body, _ := json.Marshal(payload)
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, os.Getenv("SUI_RPC_URL"), strings.NewReader(string(body)))
	if err != nil {
		return nil, err
	}
	request.Header.Set("Content-Type", "application/json")
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		return nil, fmt.Errorf("query Sui events: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("Sui event query returned %s", response.Status)
	}
	var page suiEventPage
	if err := json.NewDecoder(response.Body).Decode(&page); err != nil {
		return nil, err
	}
	if page.Error != nil {
		return nil, fmt.Errorf("Sui event query failed: %v", page.Error)
	}
	events := make([]map[string]any, 0, len(page.Result.Data))
	for _, item := range page.Result.Data {
		events = append(events, item.ParsedJSON)
	}
	return events, nil
}

func field(event map[string]any, name string) string { return fmt.Sprint(event[name]) }
func normalizeAddress(value string) string {
	return strings.TrimLeft(strings.ToLower(strings.TrimPrefix(value, "0x")), "0")
}
