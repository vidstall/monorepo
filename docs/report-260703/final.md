# Xaisen Project Report

## Roles and Responsibilities

### Purpose

The application separates its responsibilities into four cooperating roles: Router, Media, Coordinator, and VClient. Each role has a narrow purpose so that access decisions, live communication, shared awareness, and simulation remain independent while contributing to one complete experience.

The frontend is the public entry point for users. It is hosted as a static site in Alibaba Object Storage and presents the application experience, but it is not an operational worker role.

### Router

#### Intent

Its purpose is to connect participant demand with suitable media capacity. It acts as the decision-making bridge between the user-facing application and the live communication service.

#### How it works

- Receives a participant's request to enter a room.
- Reviews the Media workers that have announced they are available.
- Selects a suitable Media worker for the requested room.
- Provides the participant with the destination needed to join the live session.
- Keeps access decisions separate from the delivery of audio and video.

#### Interaction with other roles

##### Frontend

- Receives room requests initiated through the public website.
- Returns the selected destination so the participant can continue into the room.

##### Media

- Discovers Media workers that have announced their availability.
- Selects a Media worker and directs the participant to it.
- Leaves delivery of the live session to the selected Media worker.

##### Coordinator

- Does not depend on Coordinator to choose a Media worker.
- Benefits indirectly from the shared room awareness that Coordinator provides to Media workers.

##### VClient

- Receives VClient requests in the same way as requests from ordinary participants.
- Directs each VClient to an available Media worker.

### Media

#### Intent

Its purpose is to host real-time rooms and carry participant audio, video, and live data. It provides the environment in which participants communicate after they have been directed by the Router.

#### How it works

- Announces its identity, availability, and service details.
- Accepts participants sent by Router.
- Places each participant in the requested room.
- Carries the room's audio, video, and live data.
- Maintains the live session until participants leave.
- Works alongside other Media workers when more capacity is needed.

#### Interaction with other roles

##### Frontend

- Hosts the live experience after the participant has been directed to it.
- Supplies the room connection used by the participant-facing website.

##### Router

- Announces enough information for Router to recognize it as an available choice.
- Receives participants assigned by Router.
- Takes responsibility for the live session after the routing decision is complete.

##### Coordinator

- Shares temporary information about active rooms and Media workers.
- Uses shared room ownership information to keep participants associated with the correct Media worker.
- Updates this information as rooms are opened, used, and closed.

##### VClient

- Accepts VClient as a simulated participant.
- Treats its room activity like the activity of a normal participant.

### Coordinator

#### Intent

Its purpose is to preserve temporary operational knowledge shared by Media instances. This includes awareness of active nodes, rooms, and which Media instance is responsible for a room.

#### How it works

- Maintains temporary awareness of active Media workers.
- Records which rooms are active and which Media worker is responsible for each room.
- Helps separate Media workers share the same current view.
- Supports continuity when participants return to an existing room.
- Keeps this temporary information separate from the application's lasting public record.

#### Interaction with other roles

##### Frontend

- Does not interact directly with participants through the website.
- Supports the live experience indirectly by helping Media workers remain coordinated.

##### Router

- Does not choose the Media destination for Router.
- Supports Router decisions indirectly by helping Media workers maintain reliable room information.

##### Media

- Receives temporary updates about Media workers and their rooms.
- Gives Media workers a shared view of room ownership.
- Helps returning participants reach the Media worker already responsible for their room.

##### VClient

- Does not communicate with VClient directly.
- Is exercised indirectly when VClient joins rooms managed by participating Media workers.

### VClient

#### Intent

Its purpose is to simulate participant activity. It provides repeatable demand that can demonstrate whether the roles cooperate as intended.

#### How it works

- Requests entry to a chosen room through Router.
- Receives a selected Media destination.
- Joins the room as a simulated participant.
- Remains active for a defined period.
- Leaves the room when the simulation is complete.
- Repeats the normal participant journey without replacing the public website.

#### Interaction with other roles

##### Frontend

- Does not require the public website to perform its simulation.
- Recreates the participant journey that normally begins through the website.

##### Router

- Sends the same kind of room request as a normal participant.
- Receives the Media destination selected by Router.

##### Media

- Joins the selected Media worker as a simulated participant.
- Produces room activity that can be observed during a demonstration or test.

##### Coordinator

- Does not contact Coordinator directly.
- Exercises Coordinator-supported room awareness indirectly through the selected Media worker.

### Role relationships

| Role | Receives | Contributes | Main interactions |
|---|---|---|---|
| Router | Participant room requests | Selection and direction | Frontend, Media, VClient |
| Media | Assigned participants | Live rooms and real-time communication | Router, Coordinator, VClient |
| Coordinator | Temporary room and node activity | Shared operational awareness | Media |
| VClient | A selected room destination | Simulated participant activity | Router, Media |

### Interaction journey

1. A user begins at the frontend hosted in Alibaba Object Storage.
2. The frontend sends the participant's room request to the Router.
3. The Router identifies a suitable Media destination.
4. Media admits the participant and hosts the live room.
5. The Coordinator helps Media instances maintain shared awareness of nodes and room ownership.
6. VClient can follow the same Router-to-Media journey to simulate participant activity.

Together, these roles form one participant journey: the frontend presents the service, Router chooses a destination, Media provides the live room, Coordinator keeps Media workers aligned, and VClient reproduces the journey for demonstrations and tests.

---

## Sui Contract Philosophy and Economic System

### Purpose

The Sui contract is the public agreement and settlement layer of the application. It provides a shared record of who offers service, what that service costs, which commitments have been made, and how value should move when an agreement ends.

The contract does not host live rooms or carry audio and video. Its purpose is to create trust around the economic relationship between clients and workers while allowing the live service to remain with Router and Media workers.

### Philosophy

The contract follows three principles:

1. **Visible commitments:** workers declare their availability, price, and economic commitment before receiving work.
2. **Protected exchange:** client payment remains protected until the rental is completed or validly canceled.
3. **Shared coordination:** active workers participate in recognizing operational roles and coordinating how work is assigned.

This model reduces dependence on a single private operator. Participants rely on a common public agreement rather than on one party's internal record.

### Intent

The contract creates a marketplace between people who need communication capacity and workers who provide it. Clients should be able to understand the terms of an order before paying. Workers should be able to present their service, receive work, and earn rewards under the same visible rules.

The contract therefore separates economic responsibility from service delivery. It records the agreement and settles its outcome; workers deliver the live experience.

### Economic participants

| Participant | Economic intent | Relationship with the contract |
|---|---|---|
| Client | Obtain room capacity under known terms | Places payment, confirms completion, or requests a valid cancellation |
| General worker | Offer accountable service capacity | Declares price, availability, identity, and stake |
| Router worker | Connect demand with suitable Media capacity | Records the selected assignment and receives a routing share after completion |
| Media worker | Deliver the live communication service | Accepts assigned work and receives the main service reward after completion |
| Frontend | Make the marketplace understandable and accessible | Presents choices and carries the participant's approved actions to the contract |

### Worker commitment

A worker enters the marketplace by presenting an identity, a rental price, current availability, and a stake. The stake represents commitment to participation; it is not described as interest-bearing capital or an automatic penalty.

Workers remain responsible for keeping their status and price current. A worker can leave the marketplace and recover the stake when the worker is inactive and has no unfinished rental. This prevents withdrawal from disregarding an active obligation.

### Economic lifecycle

| Stage | Client side | Worker side | Economic result |
|---|---|---|---|
| Offer | Reviews available service and prices through the frontend | Publishes availability, price, and stake | Terms become visible before an order |
| Order | Chooses a room, capacity, and budget, then approves payment | Makes capacity available for selection | Payment is protected while the order is unresolved |
| Assignment | Waits for a service destination | Router selects suitable Media capacity | Router and Media responsibilities become associated with the order |
| Delivery | Participates in the live room | Media delivers the room; Router maintains the service relationship | Live activity occurs outside the contract |
| Completion | Confirms that the rental is complete | Becomes eligible for the agreed reward | Protected payment is released and divided |
| Cancellation | Cancels while cancellation remains valid | Is released from the unresolved order | Protected payment returns to the client |

### Reward distribution

For a routed rental, completion divides the payment according to the contribution of the two worker roles:

- **80% goes to Media** for providing the live communication capacity.
- **20% goes to Router** for discovering, selecting, and connecting the service path.

The split aligns reward with responsibility. Media receives the larger share because it carries the live service, while Router receives a smaller share for coordination and access. Payment is distributed only when the client completes the rental.

For a direct rental without routed participation, the worker providing the service receives the completed payment.

### Payment protection and cancellation

Payment is committed when an order is created but is not immediately treated as worker income. It remains associated with the unresolved rental until the client determines its valid outcome.

Completion releases the payment as a reward. Cancellation before completion returns the protected payment to the client when the rental remains eligible for cancellation. This gives both sides a clear distinction between money reserved for an agreement and money earned from completed service.

### Worker governance

The contract treats active workers as participants in the network's economic coordination. Workers can collectively recognize specialized roles, including Router, Media, and Coordinator, and can participate in decisions about room assignment.

The intent is to make authority a recognized network responsibility rather than an undocumented private decision. Governance supports the marketplace by identifying which workers may perform specialized duties and by providing a shared basis for assignment.

Governance does not replace the practical work of Router, Media, or Coordinator. It establishes the accepted economic and organizational context in which those roles operate.

### Interaction with the frontend

The frontend is the human-facing view of the contract economy. It allows a participant to:

- view workers and their current terms;
- choose a room, participant capacity, and budget;
- approve an order through a Sui wallet;
- follow the resulting rental into the live experience;
- complete or cancel a rental when appropriate; and
- perform worker actions when acting as a service provider.

The frontend does not replace the contract's public record. It presents that record in an understandable form and carries user-approved decisions between the participant and the contract.

### Interaction with workers

Workers use the contract to establish economic identity and responsibility. Their declared price and availability make them discoverable, while their stake expresses commitment. Specialized workers use the recorded roles and assignments to understand which responsibility belongs to whom.

Router reads the available service choices, selects suitable Media capacity, and associates that choice with the client's order. Media then provides the live room. After the client confirms completion, the contract settles the reward between them.

Coordinator supports temporary shared awareness during operation, but that short-lived information is separate from the contract's lasting economic record.

### Overall interaction

The complete model can be summarized as follows:

1. Workers make their service terms visible through the contract.
2. The frontend presents those terms to the client.
3. The client approves a room order and commits payment.
4. Router connects the order with suitable Media capacity.
5. Media delivers the live room outside the contract.
6. The client completes or validly cancels the rental.
7. The contract releases rewards or returns the protected payment according to that outcome.

The resulting system gives the frontend a clear marketplace to present, gives workers a consistent basis for earning rewards, and gives clients a transparent relationship between payment and delivered service.

---

## Cloud Provider and Infrastructure-as-Code Report

**Report date:** 2026-07-03  
**Offer data checked:** 2026-07-03

### Overview

| Metric | Count |
|---|---:|
| Cloud providers recognized by the application | 7 |
| Providers where the application can launch service instances | 5 |
| Providers where the application can publish the website | 5 |
| Providers supporting both needs | 4 |
| Services the administrator can manage | 5 |
| Supported Sui networks | 3 |

The five managed services are the public website, Router, Media, Coordinator, and VClient. The application can be prepared for the Sui development, test, or main network.

### How the application controls its services

The administrator controls the deployment from one application entry point. From there, the administrator can:

- launch a new named service with a chosen cloud provider;
- pause a service without losing its identity;
- restart a service when it needs to be refreshed;
- remove a service that is no longer required; and
- publish or update the public website.

The application keeps a record of the desired services and their current state. When the administrator requests a change, it asks the selected cloud provider to make the matching change and then prepares the chosen worker to perform its role. This gives the administrator one consistent process even when services are spread across different providers.

### Number of services that can run

Each administrator action launches or changes one named service. The administrator can repeat that action to create several Router, Media, Coordinator, or VClient workers, and those workers can run at the same time.

The application does not impose one fixed maximum. The practical limit depends on the available credit, spending limit, and account quota of the selected cloud provider. For the accounts examined in this report:

- the tested DigitalOcean account can run up to **3** instances at the tested size;
- the Alibaba Cloud account is limited by its available trial credit and hourly allowance; and
- the Microsoft Azure student account is limited by its remaining student credit and the provider's account quotas.

These figures describe the tested accounts, not a universal limit for every user.

### How a worker begins operating

After a service instance is created, the application prepares it and starts the selected worker automatically. The worker then:

- receives the information needed for its assigned role;
- joins the selected Sui network;
- announces its identity and service details in the shared public record;
- regularly confirms that it remains available; and
- marks itself unavailable when it shuts down normally.

This process allows a newly launched worker to join the application without requiring participants to know where or how it was created.

### How workers find and communicate with one another

Workers use the shared public record to announce their role, address, price, and availability. This allows Router workers to find active Media workers without relying on a private list maintained by one operator.

Their cooperation follows a clear sequence:

- Router reviews the available Media workers and selects one for a participant's room request.
- Router gives the participant the destination needed to join that Media worker.
- Media workers use Coordinator to share temporary knowledge about active rooms and which Media worker is responsible for each room.
- Coordinator announces its own availability in the same public record, allowing its role to be recognized by the wider application.
- VClient follows the same Router-to-Media journey as a normal participant when the application is being demonstrated or checked.

The public record supports discovery and accountability, while Coordinator supports short-lived information needed during live activity.

### Provider availability and free-access comparison

| Provider | Service instances managed by the application | Website storage managed by the application | General free access relevant to this application | Student-specific benefit |
|---|:---:|:---:|---|---|
| AWS | Yes | Yes | New customers receive **US$100** at signup and can earn **up to US$100 more**; free-plan access lasts **up to 6 months**. Eligible EC2 types include `t3.micro`, which matches the app default. | No separate student-only infrastructure credit verified; students can use the general new-customer offer. |
| Google Cloud | Yes | Yes | **US$300 for 90 days**; Always Free includes **1 `e2-micro` VM/month**, **30 GB** standard persistent disk, **5 GB-month** Cloud Storage, **5,000 Class A** and **50,000 Class B** storage operations/month in eligible US regions. | No direct student cloud-billing credit verified. The student program provides **200 Google Skills credits for 1 year**, which are training credits rather than infrastructure credit. |
| Microsoft Azure | Yes | No | Free-service quotas include **750 hours/month** of eligible Linux burstable VMs for **12 months** and **5 GB** locally redundant hot Blob Storage for **12 months**. The app does not currently provision Azure object storage. | Azure for Students provides **US$100 for 12 months**, renewable annually while eligible, with **no credit card required**. The verified account has **US$100 remaining** and expires on **2027-06-26**. |
| Alibaba Cloud | Yes | Yes | The verified ECS trial account has **US$90 credit**, a maximum covered rate of **US$0.25/hour**, **200 GiB/month** free internet traffic outside mainland China, and **20 GiB/month** inside mainland China. Its trial period is **2026-06-05 to 2026-09-05**. New-user OSS trials separately provide **500 GB for 1 month** for individuals. | No student-specific general infrastructure credit verified. |
| DigitalOcean | Yes | Yes | Promotional credit is account- and campaign-dependent; no permanent VM or object-storage free tier was verified. The tested account can create **3 droplets** using a **4-vCPU, 8-GB RAM** configuration. | The GitHub Student Developer Pack offer provides **US$200 for 12 months** for eligible new student accounts; current exclusions and availability must be checked when claiming. |
| Tencent Cloud | No | No | Product-specific free tiers exist, but no verified free VM or object-storage allowance is usable through the app because those provisioning adapters are not implemented. | No student-specific general infrastructure credit verified. |
| Cloudflare | No | Yes | R2 includes **10 GB-month** storage, **1 million Class A operations/month**, **10 million Class B operations/month**, and **zero egress fees**. | No student-specific infrastructure credit is required for the R2 free allowance. |

### Suitability for the application

| Requirement | Providers manageable by the application | Providers with a directly relevant verified free or student allowance |
|---|---|---|
| Running workers | AWS, Google Cloud, Microsoft Azure, Alibaba Cloud, DigitalOcean | AWS, Google Cloud, Microsoft Azure, Alibaba Cloud trial, DigitalOcean student credit |
| Hosting the public website | AWS, Google Cloud, Alibaba Cloud, DigitalOcean, Cloudflare | AWS credit, Google Cloud, Alibaba Cloud trial, DigitalOcean student credit, Cloudflare R2 |
| Both needs under one provider | AWS, Google Cloud, Alibaba Cloud, DigitalOcean | All four have a general trial, free allowance, or student credit |

### Verified account limits

| Provider | Verified capacity | Validity or balance |
|---|---|---|
| Alibaba Cloud | ECS credit ceiling of **US$0.25/hour**; **200 GiB/month** outbound traffic outside mainland China; **20 GiB/month** inside mainland China | **US$90** total credit; **2026-06-05 to 2026-09-05** |
| DigitalOcean | **3 droplets** at the tested **4-vCPU, 8-GB RAM** configuration | Limited by the account's promotional credit and current pricing |
| Microsoft Azure | Azure for Students infrastructure credit | **US$100 remaining**; expires **2027-06-26** |

These are observed limits for the tested accounts and offers, not universal account quotas.

### Conclusion

- **7** cloud providers are recognized.
- **5** can run service instances and **5** can host the public website.
- **4** can supply both resource types required for a single-provider deployment.
- **2** providers have a verified student-specific infrastructure credit: Microsoft Azure and DigitalOcean.
- **3** providers have continuing resource-level free allowances relevant to this app: AWS, Google Cloud, and Cloudflare.
- Alibaba Cloud provides time- or product-limited trials; Tencent Cloud is not currently provisionable by this app.

### Future work

#### Service monitoring

The current application can launch, pause, restart, and remove services, but it does not yet provide one place for the administrator to continuously observe them. Future work should provide a simple view showing:

- whether each service is reachable;
- when it last confirmed that it was active;
- which rooms and workers are currently active;
- whether a service has stopped unexpectedly; and
- whether cloud credit or account limits are close to being reached.

#### Test-scenario creation

VClient can imitate a participant, but the application does not yet create complete test scenarios for the administrator. Future work should allow the administrator to describe a scenario by choosing:

- the number of simulated participants;
- the rooms they should join;
- how long they should remain active;
- whether several Media workers should be involved; and
- the expected result used to decide whether the scenario succeeded.

The application could then start the required VClients, follow their progress, and present a plain-language summary of the outcome.

### Sources

- [AWS Free Tier](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-FAQ.html)
- [AWS EC2 Free Tier eligibility](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-free-tier-usage.html)
- [Google Cloud Free Program](https://docs.cloud.google.com/free/docs/free-cloud-features)
- [Google Cloud student program](https://cloud.google.com/edu/students)
- [Azure for Students](https://azure.microsoft.com/en-us/free/students)
- [Alibaba Cloud free trials](https://www.alibabacloud.com/help/en/user-center/product-overview/learn-about-free-trials)
- [Alibaba Cloud OSS new-user trial](https://www.alibabacloud.com/help/en/oss/free-quota-for-new-users)
- [DigitalOcean student offer information](https://www.digitalocean.com/community/questions/question-on-payment)
- [GitHub Student Developer Pack](https://education.github.com/pack)
- [Tencent Cloud free-tier documentation](https://www.tencentcloud.com/document/product/583/12282)
- [Cloudflare R2 pricing](https://www.cloudflare.com/products/r2/)

Free tiers, credits, regions, eligibility rules, and expiration periods can change. Values above are a dated comparison, not a billing guarantee.

---

## Test Results and Version Evolution

### Purpose

This report records the observed proof-of-concept results from version 1.0.0 and the partial validation completed for version 2.0.0. It distinguishes working evidence from intended behavior so that the current state is represented accurately.

Version 1.0.0 demonstrated that the central idea could work, but its accumulated technical debt made continued development difficult. Version 2.0.0 was therefore rebuilt as a monorepo with clearer boundaries between the frontend, contract, Router, Media, Coordinator, and supporting tools.

Version 2.0.0 is not currently validated as a complete running system. Only the frontend, Router, and contract relationship has been successfully tested.

### Evaluation philosophy

The purpose of the test was to verify the participant journey rather than to measure internal implementation details. The key questions were:

- Can two different client devices enter the same room?
- Can the system direct them to a remote Media worker?
- Can they exchange live communication?
- Is the experience understandable and acceptable to the user?

This approach treats success as an observable service outcome. A feature is considered validated only when it was exercised in the stated scenario.

### Version 1.0.0 test scenario

The version 1.0.0 proof of concept used the following environment:

| Participant or role | Quantity | Location |
|---|---:|---|
| Frontend | 1 | Local home computer |
| PC client | 1 | Home network |
| Mobile client | 1 | Home network |
| Router | 1 | Alibaba Cloud |
| SFU/Media worker | 1 | Alibaba Cloud |

The frontend ran locally, so the test did not encounter the secure public-access requirements introduced when the frontend was later moved to cloud object storage.

### Version 1.0.0 observed results

| Test area | Result | Observation |
|---|---|---|
| Two-device room entry | Passed | The PC and mobile client entered the same room through the remote service path. |
| Video exchange | Passed | Both clients exchanged video successfully. |
| Voice exchange | Failed | Voice was not exchanged between the clients. The cause was not confirmed. |
| Router-to-Media journey | Passed | The participant journey reached the Alibaba-hosted Media worker. |
| Two-client user experience | Acceptable | The experience was judged good and acceptable for the tested scale. |

The result validated the basic concept of separating user access, routing decisions, and live Media delivery. It did not validate reliable audio, larger participant groups, multiple Routers, multiple Media workers, or long-duration operation.

### Lessons carried into version 2.0.0

The version 1.0.0 implementation assumed a relatively fixed environment. The local frontend avoided public secure-access concerns, and important relationships between Router and Media depended on prearranged information. This was sufficient for a small proof of concept but was not a suitable foundation for a broader worker marketplace.

Version 2.0.0 changes the philosophy from fixed infrastructure to discoverable workers:

- The contract acts as a public service directory for locating approved roles and available Media capacity.
- The Router interprets the requested room, participant capacity, and budget before selecting Media service.
- Router and Media establish the information needed for a session dynamically rather than depending on a permanently shared secret.
- Coordinator provides temporary shared awareness when multiple Media instances must cooperate.
- The frontend is hosted independently in Alibaba Object Storage instead of being tied to a local computer.

These changes preserve the participant experience while making the relationships between roles more explicit and less dependent on fixed assumptions.

### Public frontend access

Moving the frontend from localhost to Alibaba Object Storage introduced a secure-access requirement that was not present in the version 1.0.0 test. The public frontend needed a trusted way to reach cloud workers.

Version 2.0.0 uses `sslip.io` to provide a hostname derived from a worker's public address. This allows the browser-facing service to use a trusted public name while still referring to the intended worker. The purpose is continuity between a cloud-hosted frontend and independently hosted workers, not centralized control of those workers.

### Version 2.0.0 observed results

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

### Intended economic interaction in version 2.0.0

The version 2.0.0 flow is designed to connect user demand with worker capacity through a visible economic agreement:

1. Media workers publish their availability and rental terms through the contract.
2. The frontend allows the user to describe the room, participant capacity, and budget.
3. The contract records the user's order and protects the committed payment.
4. Router discovers suitable Media workers and matches the order with available service.
5. Media hosts the room while Router maintains the relationship between the order and the selected service.
6. Completion settles the economic reward between the contributing workers.

This complete economic journey is the intended model, but it has not yet been validated end to end in version 2.0.0.

### Coordinator intent

Coordinator is a shared temporary state role for Media workers. It allows separate Media instances to maintain a common understanding of active nodes, rooms, and room ownership.

Coordinator does not carry audio or video and does not replace the contract. The contract remains the public economic and role directory; Coordinator supports short-lived operational continuity during live service. This multi-instance behavior remains untested in the current v2 result.

### Overall assessment

Version 1.0.0 proved that two clients could use a remote Router and Media worker to join a room and exchange video with an acceptable user experience. Its voice failure remains unresolved, and its fixed assumptions limited its value as a long-term foundation.

Version 2.0.0 addresses those limitations through clearer role separation, contract-based discovery, independent frontend hosting, dynamic Router-to-Media relationships, and shared Media coordination. The frontend, Router, and contract connection has been validated successfully. Media delivery, Coordinator participation, the complete economic lifecycle, and two-client audio/video remain future validation work.
