# Cloud Provider and Infrastructure-as-Code Report

**Report date:** 2026-07-03  
**Offer data checked:** 2026-07-03

## Overview

| Metric | Count |
|---|---:|
| Cloud providers recognized by the application | 7 |
| Providers where the application can launch service instances | 5 |
| Providers where the application can publish the website | 5 |
| Providers supporting both needs | 4 |
| Services the administrator can manage | 5 |
| Supported Sui networks | 3 |

The five managed services are the public website, Router, Media, Coordinator, and VClient. The application can be prepared for the Sui development, test, or main network.

## How the application controls its services

The administrator controls the deployment from one application entry point. From there, the administrator can:

- launch a new named service with a chosen cloud provider;
- pause a service without losing its identity;
- restart a service when it needs to be refreshed;
- remove a service that is no longer required; and
- publish or update the public website.

The application keeps a record of the desired services and their current state. When the administrator requests a change, it asks the selected cloud provider to make the matching change and then prepares the chosen worker to perform its role. This gives the administrator one consistent process even when services are spread across different providers.

## Number of services that can run

Each administrator action launches or changes one named service. The administrator can repeat that action to create several Router, Media, Coordinator, or VClient workers, and those workers can run at the same time.

The application does not impose one fixed maximum. The practical limit depends on the available credit, spending limit, and account quota of the selected cloud provider. For the accounts examined in this report:

- the tested DigitalOcean account can run up to **3** instances at the tested size;
- the Alibaba Cloud account is limited by its available trial credit and hourly allowance; and
- the Microsoft Azure student account is limited by its remaining student credit and the provider's account quotas.

These figures describe the tested accounts, not a universal limit for every user.

## How a worker begins operating

After a service instance is created, the application prepares it and starts the selected worker automatically. The worker then:

- receives the information needed for its assigned role;
- joins the selected Sui network;
- announces its identity and service details in the shared public record;
- regularly confirms that it remains available; and
- marks itself unavailable when it shuts down normally.

This process allows a newly launched worker to join the application without requiring participants to know where or how it was created.

## How workers find and communicate with one another

Workers use the shared public record to announce their role, address, price, and availability. This allows Router workers to find active Media workers without relying on a private list maintained by one operator.

Their cooperation follows a clear sequence:

- Router reviews the available Media workers and selects one for a participant's room request.
- Router gives the participant the destination needed to join that Media worker.
- Media workers use Coordinator to share temporary knowledge about active rooms and which Media worker is responsible for each room.
- Coordinator announces its own availability in the same public record, allowing its role to be recognized by the wider application.
- VClient follows the same Router-to-Media journey as a normal participant when the application is being demonstrated or checked.

The public record supports discovery and accountability, while Coordinator supports short-lived information needed during live activity.

## Provider availability and free-access comparison

| Provider | Service instances managed by the application | Website storage managed by the application | General free access relevant to this application | Student-specific benefit |
|---|:---:|:---:|---|---|
| AWS | Yes | Yes | New customers receive **US$100** at signup and can earn **up to US$100 more**; free-plan access lasts **up to 6 months**. Eligible EC2 types include `t3.micro`, which matches the app default. | No separate student-only infrastructure credit verified; students can use the general new-customer offer. |
| Google Cloud | Yes | Yes | **US$300 for 90 days**; Always Free includes **1 `e2-micro` VM/month**, **30 GB** standard persistent disk, **5 GB-month** Cloud Storage, **5,000 Class A** and **50,000 Class B** storage operations/month in eligible US regions. | No direct student cloud-billing credit verified. The student program provides **200 Google Skills credits for 1 year**, which are training credits rather than infrastructure credit. |
| Microsoft Azure | Yes | No | Free-service quotas include **750 hours/month** of eligible Linux burstable VMs for **12 months** and **5 GB** locally redundant hot Blob Storage for **12 months**. The app does not currently provision Azure object storage. | Azure for Students provides **US$100 for 12 months**, renewable annually while eligible, with **no credit card required**. The verified account has **US$100 remaining** and expires on **2027-06-26**. |
| Alibaba Cloud | Yes | Yes | The verified ECS trial account has **US$90 credit**, a maximum covered rate of **US$0.25/hour**, **200 GiB/month** free internet traffic outside mainland China, and **20 GiB/month** inside mainland China. Its trial period is **2026-06-05 to 2026-09-05**. New-user OSS trials separately provide **500 GB for 1 month** for individuals. | No student-specific general infrastructure credit verified. |
| DigitalOcean | Yes | Yes | Promotional credit is account- and campaign-dependent; no permanent VM or object-storage free tier was verified. The tested account can create **3 droplets** using a **4-vCPU, 8-GB RAM** configuration. | The GitHub Student Developer Pack offer provides **US$200 for 12 months** for eligible new student accounts; current exclusions and availability must be checked when claiming. |
| Tencent Cloud | No | No | Product-specific free tiers exist, but no verified free VM or object-storage allowance is usable through the app because those provisioning adapters are not implemented. | No student-specific general infrastructure credit verified. |
| Cloudflare | No | Yes | R2 includes **10 GB-month** storage, **1 million Class A operations/month**, **10 million Class B operations/month**, and **zero egress fees**. | No student-specific infrastructure credit is required for the R2 free allowance. |

## Suitability for the application

| Requirement | Providers manageable by the application | Providers with a directly relevant verified free or student allowance |
|---|---|---|
| Running workers | AWS, Google Cloud, Microsoft Azure, Alibaba Cloud, DigitalOcean | AWS, Google Cloud, Microsoft Azure, Alibaba Cloud trial, DigitalOcean student credit |
| Hosting the public website | AWS, Google Cloud, Alibaba Cloud, DigitalOcean, Cloudflare | AWS credit, Google Cloud, Alibaba Cloud trial, DigitalOcean student credit, Cloudflare R2 |
| Both needs under one provider | AWS, Google Cloud, Alibaba Cloud, DigitalOcean | All four have a general trial, free allowance, or student credit |

## Verified account limits

| Provider | Verified capacity | Validity or balance |
|---|---|---|
| Alibaba Cloud | ECS credit ceiling of **US$0.25/hour**; **200 GiB/month** outbound traffic outside mainland China; **20 GiB/month** inside mainland China | **US$90** total credit; **2026-06-05 to 2026-09-05** |
| DigitalOcean | **3 droplets** at the tested **4-vCPU, 8-GB RAM** configuration | Limited by the account's promotional credit and current pricing |
| Microsoft Azure | Azure for Students infrastructure credit | **US$100 remaining**; expires **2027-06-26** |

These are observed limits for the tested accounts and offers, not universal account quotas.

## Conclusion

- **7** cloud providers are recognized.
- **5** can run service instances and **5** can host the public website.
- **4** can supply both resource types required for a single-provider deployment.
- **2** providers have a verified student-specific infrastructure credit: Microsoft Azure and DigitalOcean.
- **3** providers have continuing resource-level free allowances relevant to this app: AWS, Google Cloud, and Cloudflare.
- Alibaba Cloud provides time- or product-limited trials; Tencent Cloud is not currently provisionable by this app.

## Future work

### Service monitoring

The current application can launch, pause, restart, and remove services, but it does not yet provide one place for the administrator to continuously observe them. Future work should provide a simple view showing:

- whether each service is reachable;
- when it last confirmed that it was active;
- which rooms and workers are currently active;
- whether a service has stopped unexpectedly; and
- whether cloud credit or account limits are close to being reached.

### Test-scenario creation

VClient can imitate a participant, but the application does not yet create complete test scenarios for the administrator. Future work should allow the administrator to describe a scenario by choosing:

- the number of simulated participants;
- the rooms they should join;
- how long they should remain active;
- whether several Media workers should be involved; and
- the expected result used to decide whether the scenario succeeded.

The application could then start the required VClients, follow their progress, and present a plain-language summary of the outcome.

## Sources

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
