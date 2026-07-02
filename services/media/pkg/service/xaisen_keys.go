package service

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"os"

	"github.com/livekit/livekit-server/pkg/config"
	redisLiveKit "github.com/livekit/protocol/redis"
)

const xaisenClusterKeyRedisKey = "xaisen:livekit:cluster-credential:v1"

type clusterCredential struct {
	APIKey string `json:"apiKey"`
	Secret string `json:"secret"`
}

// EnsureXaisenClusterKey atomically bootstraps one LiveKit signing credential
// for every media node sharing Redis. It removes the need to distribute a
// static LIVEKIT_KEYS value to routers or media containers.
func EnsureXaisenClusterKey(ctx context.Context, conf *config.Config) error {
	if len(conf.Keys) > 0 || os.Getenv("XAISEN_AUTO_CLUSTER_KEY") == "false" {
		return nil
	}
	if !conf.Redis.IsConfigured() {
		return fmt.Errorf("Redis is required when XAISEN_AUTO_CLUSTER_KEY is enabled")
	}
	client, err := redisLiveKit.GetRedisClient(&conf.Redis)
	if err != nil {
		return err
	}
	defer client.Close()

	credential, err := newClusterCredential()
	if err != nil {
		return err
	}
	encoded, _ := json.Marshal(credential)
	created, err := client.SetNX(ctx, xaisenClusterKeyRedisKey, encoded, 0).Result()
	if err != nil {
		return err
	}
	if !created {
		encoded, err = client.Get(ctx, xaisenClusterKeyRedisKey).Bytes()
		if err != nil {
			return err
		}
		if err := json.Unmarshal(encoded, &credential); err != nil {
			return fmt.Errorf("decode generated LiveKit credential: %w", err)
		}
	}
	conf.Keys = map[string]string{credential.APIKey: credential.Secret}
	return nil
}

func newClusterCredential() (clusterCredential, error) {
	key := make([]byte, 12)
	secret := make([]byte, 32)
	if _, err := rand.Read(key); err != nil {
		return clusterCredential{}, err
	}
	if _, err := rand.Read(secret); err != nil {
		return clusterCredential{}, err
	}
	return clusterCredential{
		APIKey: "xk_" + base64.RawURLEncoding.EncodeToString(key),
		Secret: base64.RawURLEncoding.EncodeToString(secret),
	}, nil
}
