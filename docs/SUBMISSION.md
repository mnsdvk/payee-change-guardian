# Devpost submission: field by field

## General info
**Project name:** PayeeChange Guardian

**Elevator pitch (179 / 200):**
Payment-redirect fraud starts with an email. Guardian holds a supplier's bank-detail change and verifies it only through the contact already on record, never the one in the email.

## Project story (paste into "About the project")

## Inspiration
Invoice-redirection fraud works because the fake email carries its own proof: a new bank account *and* a friendly "please confirm on this number". An accounts-payable clerk who calls that number has just verified the fraudster with the fraudster. We wanted a system where an email can *request* a payment change but can never *authorize* one.

## What it does
PayeeChange Guardian sits between a supplier's "we changed banks" email and the payment record.
- It **holds** the change immediately. The account on file stays in force.
- It scores the request with deterministic signals (changed account, new contact details, unseen sender domain, failed SPF/DKIM, pressure wording, unusual amount).
- It **verifies only through the contact already in the trusted vendor registry**. Any phone number or address inside the email is ignored and shown as "never used".
- The registered contact gets one-time Yes / No links. A "No" blocks the change; a "Yes" still has to pass extra checks (IBAN checksum, account not registered to another vendor) before the record is updated. Anything unclear goes to a human approver.
- Every step is on an audit timeline, and the dashboard shows the account before and after, so you can see whether protected data actually changed.
- An AI analyst adds a plain-English note ("lookalike domain, urgency, redirected contact") to help the clerk. It is advisory only.

## How we built it
Everything is deployed with AWS SAM in us-east-1: API Gateway and Lambda (intake, policy, dashboard), **Step Functions with `waitForTaskToken`** to hold the change until the supplier answers, DynamoDB (trusted registry and cases), EventBridge and SNS (alerts for blocked, escalated and stuck cases), SSM Parameter Store (API key), and **Amazon SES v2** (`sesv2.send_email`) for verification and approver mail. Confirm pages use GET to preview and POST to decide, with random one-time tokens, so email scanners that prefetch links cannot answer for the supplier.

The AI is deliberately boxed in. A separate background Lambda asks an external LLM (Gemini free tier today; Amazon Bedrock is a one-line setting) for a short note, and a classifier turns free-text replies into a label only. The model never chooses a destination, never approves, and a DENY always blocks. If the model is slow or down, the case still works and the page says so.

WhatsApp (End User Messaging Social) and SMS (End User Messaging SMS) are implemented in the same channel layer and unit-tested against the SDK call shapes. They are not enabled in the deployed account because the service access was not available to us.

## Challenges we ran into
- **Service access.** Our AWS free plan blocked Bedrock, WhatsApp and SMS. We rebuilt the live path around SES and kept the other channels behind a setting.
- **Email security scanners.** Link prefetching can "click" a confirmation. We moved the decision behind a POST and burn tokens on first use.
- **Keeping the model out of the blast radius.** Prompt-injection in the email must not change where verification goes, so the destination is never an input to the model. We test this.
- **Free-tier LLM latency.** Notes were timing out, so the AI moved to an asynchronous worker with model fallback; the decision path never waits on it.

## Accomplishments that we're proud of
- The attack case ends blocked with the registered account untouched, and the legitimate case ends approved, both visible end to end in a live deployment.
- 38 automated tests, including token reuse, masked public views, conditional replies never approving, and model failure never breaking a case.
- A dashboard that explains the decision instead of just showing a score.

## What we learned
Put the model where it can explain, not where it can be fooled. The strongest control here is not smarter AI. It is refusing to trust the channel the request arrived on.

## What's next for PayeeChange Guardian
Enable WhatsApp and SMS fallbacks, add Amazon Bedrock AgentCore for multi-step case handling, connect to a real ERP or payment system, and put the dashboard behind SSO with maker-checker approvals.

## Built with (up to 25 tags)
Amazon SES, AWS Lambda, AWS Step Functions, Amazon DynamoDB, Amazon EventBridge, Amazon SNS, Amazon API Gateway, AWS Systems Manager Parameter Store, AWS SAM, AWS CloudFormation, Amazon S3, AWS Budgets, Python, Google Gemini, HTML, JavaScript

## "Try it out" links
- Live dashboard: `<your DashboardUrl>`
- Code: `<your GitHub repo URL>`

## Other form fields
- **AWS Partner Company Name:** GlobalLogic
- **Which CDS service(s) does your solution use?** Select **SES only**. WhatsApp, SMS and RCS are not used at runtime in this deployment.
- **Did you use AWS End User Messaging Social (WhatsApp)?** No. (Leave the description blank.)
- **Repository:** public GitHub repo with the MIT `LICENSE` (visible in the About section), or private shared with testing@devpost.com and aws-cds-partner@amazon.com.
- **Architecture diagram:** upload `docs/architecture.png`.
- **ACE Opportunity ID:** required. Enter only a real ID from AWS Partner Central.
- **Demo video:** public or unlisted YouTube/Vimeo link, about 3 minutes (only the first 3 minutes are reviewed).
- **Image gallery:** screenshots of the home page, a blocked case, an approved case, and the architecture diagram.

## Demo video script (about 3 minutes)
1. **0:00 The problem (20s).** "A supplier email says: we changed banks, confirm on this new number. Most teams call that number. That's how the fraud works." Show the fraud email text.
2. **0:20 The idea (15s).** Home page: "An email can request a change. It cannot authorize one." Point at the gate diagram.
3. **0:35 Attack (60s).** Click **Fraud attempt**. Show the held banner, risk score 100 and evidence list. Point at the diagram: the fake phone number is crossed out as "ignored"; verification goes to the registered email. Show the AI note when it appears ("advisory only"). Answer **No, we did not**. Banner turns red: blocked. Show account before and after: unchanged.
4. **1:35 Real change (40s).** Click **Real supplier change**. Same safeguards, lower risk. Answer **Yes**. Show it approved and the account updated.
5. **2:15 Guardrails (30s).** Type "yes, but only if you pay by Friday". It goes to a person, not approved. Mention one-time scanner-safe links and that the model is advisory.
6. **2:45 Architecture (15s).** Show the diagram: SES live, Step Functions hold, DynamoDB registry, AI worker. Say plainly: WhatsApp and SMS are built but not enabled here; the AI is an external model that can be swapped for Bedrock.
