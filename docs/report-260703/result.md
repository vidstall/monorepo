# Test Results and Version Evolution

## Purpose

This report records the observed proof-of-concept results from version 1.0.0 and the partial validation completed for version 2.0.0. It distinguishes working evidence from intended behavior so that the current state is represented accurately.

Version 1.0.0 demonstrated that the central idea could work, but its accumulated technical debt made continued development difficult. Version 2.0.0 was therefore rebuilt as a monorepo with clearer boundaries between the frontend, contract, Router, Media, Coordinator, and supporting tools.

Version 2.0.0 is not currently validated as a complete running system. Only the frontend, Router, and contract relationship has been successfully tested.

## Evaluation philosophy

The purpose of the test was to verify the participant journey rather than to measure internal implementation details. The key questions were:

- Can two different client devices enter the same room?
- Can the system direct them to a remote Media worker?
- Can they exchange live communication?
- Is the experience understandable and acceptable to the user?

This approach treats success as an observable service outcome. A feature is considered validated only when it was exercised in the stated scenario.

## Version 1.0.0 test scenario

The version 1.0.0 proof of concept used the following environment:

| Participant or role | Quantity | Location |
|---|---:|---|
| Frontend | 1 | Local home computer |
| PC client | 1 | Home network |
| Mobile client | 1 | Home network |
| Router | 1 | Alibaba Cloud |
| SFU/Media worker | 1 | Alibaba Cloud |

The frontend ran locally, so the test did not encounter the secure public-access requirements introduced when the frontend was later moved to cloud object storage.

## Version 1.0.0 observed results

| Test area | Result | Observation |
|---|---|---|
| Two-device room entry | Passed | The PC and mobile client entered the same room through the remote service path. |
| Video exchange | Passed | Both clients exchanged video successfully. |
| Voice exchange | Failed | Voice was not exchanged between the clients. The cause was not confirmed. |
| Router-to-Media journey | Passed | The participant journey reached the Alibaba-hosted Media worker. |
| Two-client user experience | Acceptable | The experience was judged good and acceptable for the tested scale. |

The result validated the basic concept of separating user access, routing decisions, and live Media delivery. It did not validate reliable audio, larger participant groups, multiple Routers, multiple Media workers, or long-duration operation.

## Lessons carried into version 2.0.0

The version 1.0.0 implementation assumed a relatively fixed environment. The local frontend avoided public secure-access concerns, and important relationships between Router and Media depended on prearranged information. This was sufficient for a small proof of concept but was not a suitable foundation for a broader worker marketplace.

Version 2.0.0 changes the philosophy from fixed infrastructure to discoverable workers:

- The contract acts as a public service directory for locating approved roles and available Media capacity.
- The Router interprets the requested room, participant capacity, and budget before selecting Media service.
- Router and Media establish the information needed for a session dynamically rather than depending on a permanently shared secret.
- Coordinator provides temporary shared awareness when multiple Media instances must cooperate.
- The frontend is hosted independently in Alibaba Object Storage instead of being tied to a local computer.

These changes preserve the participant experience while making the relationships between roles more explicit and less dependent on fixed assumptions.

## Public frontend access

Moving the frontend from localhost to Alibaba Object Storage introduced a secure-access requirement that was not present in the version 1.0.0 test. The public frontend needed a trusted way to reach cloud workers.

Version 2.0.0 uses `sslip.io` to provide a hostname derived from a worker's public address. This allows the browser-facing service to use a trusted public name while still referring to the intended worker. The purpose is continuity between a cloud-hosted frontend and independently hosted workers, not centralized control of those workers.

## Version 2.0.0 observed results

| Test area | Result | Observation |
|---|---|---|
| Frontend-to-contract connection | Passed | The frontend successfully interacted with the Sui contract. |
| Frontend discovery of Router | Passed | The frontend used the contract's public record to locate the Router. |
| Frontend-to-Router connection | Passed | The frontend successfully reached the discovered Router. |
| Router discovery of Media | Not fully tested | The intended contract-based discovery exists, but the complete running journey was not validated. |
| Router-to-Media session | Not tested | Dynamic Media access and the live room path remain to be validated together. |
| Coordinator participation | Not tested | Shared state between multiple Media instances was not included in the completed test. |
| End-to-end video | Not tested | No complete v2 two-client video result is available. |
| End-to-end voice | Not tested | No complete v2 audio result is available. |

The successful v2 result is therefore limited but meaningful: the frontend can use the contract as a public directory, discover the Router, and establish the first stage of the participant journey.

## Intended economic interaction in version 2.0.0

The version 2.0.0 flow is designed to connect user demand with worker capacity through a visible economic agreement:

1. Media workers publish their availability and rental terms through the contract.
2. The frontend allows the user to describe the room, participant capacity, and budget.
3. The contract records the user's order and protects the committed payment.
4. Router discovers suitable Media workers and matches the order with available service.
5. Media hosts the room while Router maintains the relationship between the order and the selected service.
6. Completion settles the economic reward between the contributing workers.

This complete economic journey is the intended model, but it has not yet been validated end to end in version 2.0.0.

## Coordinator intent

Coordinator is a shared temporary state role for Media workers. It allows separate Media instances to maintain a common understanding of active nodes, rooms, and room ownership.

Coordinator does not carry audio or video and does not replace the contract. The contract remains the public economic and role directory; Coordinator supports short-lived operational continuity during live service. This multi-instance behavior remains untested in the current v2 result.

## Overall assessment

Version 1.0.0 proved that two clients could use a remote Router and Media worker to join a room and exchange video with an acceptable user experience. Its voice failure remains unresolved, and its fixed assumptions limited its value as a long-term foundation.

Version 2.0.0 addresses those limitations through clearer role separation, contract-based discovery, independent frontend hosting, dynamic Router-to-Media relationships, and shared Media coordination. The frontend, Router, and contract connection has been validated successfully. Media delivery, Coordinator participation, the complete economic lifecycle, and two-client audio/video remain future validation work.
