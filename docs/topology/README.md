# How This System Is Put Together

This document explains, in plain language, who and what is involved in this
video-calling system and how the pieces fit together. It is organized around
four groups: the people who use it, the machines that do the work, the
shared record both sides rely on to find each other, and finally a picture
of how it all connects.

## 1. User side

These are the everyday people who want to make a video call — no different
from opening any other video-chat website.

- A user opens a website and joins a call. There's nothing to install.
- Behind the scenes, the website looks the user up in a shared, public record
  (described in "Contract side" below) to find which workers are currently
  available, then connects to them so the call is smooth and low-lag.
- Users don't need to understand how any of the rest of this system works.
  They just see a normal video call.

## 2. Worker side

Workers are the computers that actually make a call happen — they carry the
video and audio, help people find each other, and keep an eye on each other's
performance. Anyone can offer to run one, but they have to put down a deposit
first and get watched. There are a few different jobs a worker can be given:

- **Traffic carriers** — pass the actual audio and video between the people
  on a call, as fast and reliably as possible.
- **Matchmakers** — help two people's devices find and connect to each other
  when a call starts.
- **Inspectors** — constantly check that other workers are online and doing
  their job properly, and report back if something looks wrong.

Because running a worker costs money to set up (the deposit) and workers are
scored on how well they perform, there's a real incentive to keep the service
fast and honest — a worker that misbehaves or goes offline risks losing its
job and its deposit.

Workers use the same shared record described below to find people who need a
call carried, and to check up on each other's status.

## 3. Contract side

Neither users nor workers talk to each other directly out of nowhere — they
first find each other through one shared, tamper-proof record that everyone
in the system can read and write to. Think of it as a public directory or
notice board rather than any single company's private database — nobody
owns it, and nobody can quietly rewrite what's on it.

- **Users check it to find workers.** A user's website looks at this shared
  record to see which workers are currently available before connecting.
- **Workers check it to find users, and each other.** A worker looks at the
  same shared record to see who needs a call carried, and to see the status
  of other workers around it.
- **Both sides write to it, too.** Workers list themselves and their current
  status on it; results of calls and worker performance get recorded there
  as well, so the record stays trustworthy and up to date for everyone who
  reads it next.

In short, this shared record is the one thing both the user side and the
worker side check first — it's how the two sides find each other at all.

## 4. System architecture

Putting it together, the three main parties form a **triangle**, not a
straight line:

- The **client** looks up the **contract** (the shared record) to find
  available workers.
- The **worker** looks up the same **contract** to find clients that need a
  call carried, and to check on other workers.
- Once they've found each other through the contract, the **client and
  worker talk directly** — that's the actual call audio/video.

So the contract never carries call traffic itself; it's the lookup point
both sides check first, and both sides also write their own status back to
it. Alongside this triangle, a separate monitoring layer continuously
watches call quality (things like video smoothness and connection delay),
and a set of automated tools can spin up or tear down groups of workers
across different cloud providers — which is how this system is tested at
scale before real users ever touch it.

![Topology diagram: a triangle of Client, Contract, and Worker. The client looks up available workers via the Contract; the worker looks up clients and other workers via the Contract; and the client and worker exchange call audio/video directly. A separate Monitoring box watches call quality across both.](../imgen/output/topology.png)

<sub>Diagram built from React source in [`docs/imgen/src/diagrams/topology.tsx`](../imgen/src/diagrams/topology.tsx) — run `pnpm build` in `docs/imgen/` to regenerate.</sub>
