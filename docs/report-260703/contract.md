# Sui Contract Philosophy and Economic System

## Purpose

The Sui contract is the public agreement and settlement layer of the application. It provides a shared record of who offers service, what that service costs, which commitments have been made, and how value should move when an agreement ends.

The contract does not host live rooms or carry audio and video. Its purpose is to create trust around the economic relationship between clients and workers while allowing the live service to remain with Router and Media workers.

## Philosophy

The contract follows three principles:

1. **Visible commitments:** workers declare their availability, price, and economic commitment before receiving work.
2. **Protected exchange:** client payment remains protected until the rental is completed or validly canceled.
3. **Shared coordination:** active workers participate in recognizing operational roles and coordinating how work is assigned.

This model reduces dependence on a single private operator. Participants rely on a common public agreement rather than on one party's internal record.

## Intent

The contract creates a marketplace between people who need communication capacity and workers who provide it. Clients should be able to understand the terms of an order before paying. Workers should be able to present their service, receive work, and earn rewards under the same visible rules.

The contract therefore separates economic responsibility from service delivery. It records the agreement and settles its outcome; workers deliver the live experience.

## Economic participants

| Participant | Economic intent | Relationship with the contract |
|---|---|---|
| Client | Obtain room capacity under known terms | Places payment, confirms completion, or requests a valid cancellation |
| General worker | Offer accountable service capacity | Declares price, availability, identity, and stake |
| Router worker | Connect demand with suitable Media capacity | Records the selected assignment and receives a routing share after completion |
| Media worker | Deliver the live communication service | Accepts assigned work and receives the main service reward after completion |
| Frontend | Make the marketplace understandable and accessible | Presents choices and carries the participant's approved actions to the contract |

## Worker commitment

A worker enters the marketplace by presenting an identity, a rental price, current availability, and a stake. The stake represents commitment to participation; it is not described as interest-bearing capital or an automatic penalty.

Workers remain responsible for keeping their status and price current. A worker can leave the marketplace and recover the stake when the worker is inactive and has no unfinished rental. This prevents withdrawal from disregarding an active obligation.

## Economic lifecycle

| Stage | Client side | Worker side | Economic result |
|---|---|---|---|
| Offer | Reviews available service and prices through the frontend | Publishes availability, price, and stake | Terms become visible before an order |
| Order | Chooses a room, capacity, and budget, then approves payment | Makes capacity available for selection | Payment is protected while the order is unresolved |
| Assignment | Waits for a service destination | Router selects suitable Media capacity | Router and Media responsibilities become associated with the order |
| Delivery | Participates in the live room | Media delivers the room; Router maintains the service relationship | Live activity occurs outside the contract |
| Completion | Confirms that the rental is complete | Becomes eligible for the agreed reward | Protected payment is released and divided |
| Cancellation | Cancels while cancellation remains valid | Is released from the unresolved order | Protected payment returns to the client |

## Reward distribution

For a routed rental, completion divides the payment according to the contribution of the two worker roles:

- **80% goes to Media** for providing the live communication capacity.
- **20% goes to Router** for discovering, selecting, and connecting the service path.

The split aligns reward with responsibility. Media receives the larger share because it carries the live service, while Router receives a smaller share for coordination and access. Payment is distributed only when the client completes the rental.

For a direct rental without routed participation, the worker providing the service receives the completed payment.

## Payment protection and cancellation

Payment is committed when an order is created but is not immediately treated as worker income. It remains associated with the unresolved rental until the client determines its valid outcome.

Completion releases the payment as a reward. Cancellation before completion returns the protected payment to the client when the rental remains eligible for cancellation. This gives both sides a clear distinction between money reserved for an agreement and money earned from completed service.

## Worker governance

The contract treats active workers as participants in the network's economic coordination. Workers can collectively recognize specialized roles, including Router, Media, and Coordinator, and can participate in decisions about room assignment.

The intent is to make authority a recognized network responsibility rather than an undocumented private decision. Governance supports the marketplace by identifying which workers may perform specialized duties and by providing a shared basis for assignment.

Governance does not replace the practical work of Router, Media, or Coordinator. It establishes the accepted economic and organizational context in which those roles operate.

## Interaction with the frontend

The frontend is the human-facing view of the contract economy. It allows a participant to:

- view workers and their current terms;
- choose a room, participant capacity, and budget;
- approve an order through a Sui wallet;
- follow the resulting rental into the live experience;
- complete or cancel a rental when appropriate; and
- perform worker actions when acting as a service provider.

The frontend does not replace the contract's public record. It presents that record in an understandable form and carries user-approved decisions between the participant and the contract.

## Interaction with workers

Workers use the contract to establish economic identity and responsibility. Their declared price and availability make them discoverable, while their stake expresses commitment. Specialized workers use the recorded roles and assignments to understand which responsibility belongs to whom.

Router reads the available service choices, selects suitable Media capacity, and associates that choice with the client's order. Media then provides the live room. After the client confirms completion, the contract settles the reward between them.

Coordinator supports temporary shared awareness during operation, but that short-lived information is separate from the contract's lasting economic record.

## Overall interaction

The complete model can be summarized as follows:

1. Workers make their service terms visible through the contract.
2. The frontend presents those terms to the client.
3. The client approves a room order and commits payment.
4. Router connects the order with suitable Media capacity.
5. Media delivers the live room outside the contract.
6. The client completes or validly cancels the rental.
7. The contract releases rewards or returns the protected payment according to that outcome.

The resulting system gives the frontend a clear marketplace to present, gives workers a consistent basis for earning rewards, and gives clients a transparent relationship between payment and delivered service.
