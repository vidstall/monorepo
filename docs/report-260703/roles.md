# Roles and Responsibilities

## Purpose

The application separates its responsibilities into four cooperating roles: Router, Media, Coordinator, and VClient. Each role has a narrow purpose so that access decisions, live communication, shared awareness, and simulation remain independent while contributing to one complete experience.

The frontend is the public entry point for users. It is hosted as a static site in Alibaba Object Storage and presents the application experience, but it is not an operational worker role.

## Router

### Intent

Its purpose is to connect participant demand with suitable media capacity. It acts as the decision-making bridge between the user-facing application and the live communication service.

### How it works

- Receives a participant's request to enter a room.
- Reviews the Media workers that have announced they are available.
- Selects a suitable Media worker for the requested room.
- Provides the participant with the destination needed to join the live session.
- Keeps access decisions separate from the delivery of audio and video.

### Interaction with other roles

#### Frontend

- Receives room requests initiated through the public website.
- Returns the selected destination so the participant can continue into the room.

#### Media

- Discovers Media workers that have announced their availability.
- Selects a Media worker and directs the participant to it.
- Leaves delivery of the live session to the selected Media worker.

#### Coordinator

- Does not depend on Coordinator to choose a Media worker.
- Benefits indirectly from the shared room awareness that Coordinator provides to Media workers.

#### VClient

- Receives VClient requests in the same way as requests from ordinary participants.
- Directs each VClient to an available Media worker.

## Media

### Intent

Its purpose is to host real-time rooms and carry participant audio, video, and live data. It provides the environment in which participants communicate after they have been directed by the Router.

### How it works

- Announces its identity, availability, and service details.
- Accepts participants sent by Router.
- Places each participant in the requested room.
- Carries the room's audio, video, and live data.
- Maintains the live session until participants leave.
- Works alongside other Media workers when more capacity is needed.

### Interaction with other roles

#### Frontend

- Hosts the live experience after the participant has been directed to it.
- Supplies the room connection used by the participant-facing website.

#### Router

- Announces enough information for Router to recognize it as an available choice.
- Receives participants assigned by Router.
- Takes responsibility for the live session after the routing decision is complete.

#### Coordinator

- Shares temporary information about active rooms and Media workers.
- Uses shared room ownership information to keep participants associated with the correct Media worker.
- Updates this information as rooms are opened, used, and closed.

#### VClient

- Accepts VClient as a simulated participant.
- Treats its room activity like the activity of a normal participant.

## Coordinator

### Intent

Its purpose is to preserve temporary operational knowledge shared by Media instances. This includes awareness of active nodes, rooms, and which Media instance is responsible for a room.

### How it works

- Maintains temporary awareness of active Media workers.
- Records which rooms are active and which Media worker is responsible for each room.
- Helps separate Media workers share the same current view.
- Supports continuity when participants return to an existing room.
- Keeps this temporary information separate from the application's lasting public record.

### Interaction with other roles

#### Frontend

- Does not interact directly with participants through the website.
- Supports the live experience indirectly by helping Media workers remain coordinated.

#### Router

- Does not choose the Media destination for Router.
- Supports Router decisions indirectly by helping Media workers maintain reliable room information.

#### Media

- Receives temporary updates about Media workers and their rooms.
- Gives Media workers a shared view of room ownership.
- Helps returning participants reach the Media worker already responsible for their room.

#### VClient

- Does not communicate with VClient directly.
- Is exercised indirectly when VClient joins rooms managed by participating Media workers.

## VClient

### Intent

Its purpose is to simulate participant activity. It provides repeatable demand that can demonstrate whether the roles cooperate as intended.

### How it works

- Requests entry to a chosen room through Router.
- Receives a selected Media destination.
- Joins the room as a simulated participant.
- Remains active for a defined period.
- Leaves the room when the simulation is complete.
- Repeats the normal participant journey without replacing the public website.

### Interaction with other roles

#### Frontend

- Does not require the public website to perform its simulation.
- Recreates the participant journey that normally begins through the website.

#### Router

- Sends the same kind of room request as a normal participant.
- Receives the Media destination selected by Router.

#### Media

- Joins the selected Media worker as a simulated participant.
- Produces room activity that can be observed during a demonstration or test.

#### Coordinator

- Does not contact Coordinator directly.
- Exercises Coordinator-supported room awareness indirectly through the selected Media worker.

## Role relationships

| Role | Receives | Contributes | Main interactions |
|---|---|---|---|
| Router | Participant room requests | Selection and direction | Frontend, Media, VClient |
| Media | Assigned participants | Live rooms and real-time communication | Router, Coordinator, VClient |
| Coordinator | Temporary room and node activity | Shared operational awareness | Media |
| VClient | A selected room destination | Simulated participant activity | Router, Media |

## Interaction journey

1. A user begins at the frontend hosted in Alibaba Object Storage.
2. The frontend sends the participant's room request to the Router.
3. The Router identifies a suitable Media destination.
4. Media admits the participant and hosts the live room.
5. The Coordinator helps Media instances maintain shared awareness of nodes and room ownership.
6. VClient can follow the same Router-to-Media journey to simulate participant activity.

Together, these roles form one participant journey: the frontend presents the service, Router chooses a destination, Media provides the live room, Coordinator keeps Media workers aligned, and VClient reproduces the journey for demonstrations and tests.
