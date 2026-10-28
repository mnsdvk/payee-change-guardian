# Deploy runbook (run these yourself, in your AWS account)

Use an IAM role or `aws configure sso`. Never paste keys into files or the repo.

## 0. Prerequisites
```bash
aws --version && sam --version && python3 --version   # install AWS CLI + SAM CLI if missing
aws sts get-caller-identity                           # confirm the right account
export AWS_REGION=us-east-1                           # pick a region with SES inbound + Bedrock + End User Messaging
```

## 1. Bedrock model access
Console > Amazon Bedrock > Model access > enable the model set in `BedrockModelId` (default `us.amazon.nova-micro-v1:0`).

## 2. SES
(Skip steps 3-4 of this section if you have no domain. Leave `InboundRecipient` empty and use the dashboard scenarios; the email-intake path is then off.)
1. SES > Identities > Create identity > Domain (yours). Add the DKIM CNAMEs it shows.
2. Create an Email address identity for `SesFromAddress` and one for the approver address (sandbox).
3. Add an MX record: `mail.yourdomain  MX 10  inbound-smtp.$AWS_REGION.amazonaws.com`
4. Pick the inbound address, e.g. `vendor-updates@mail.yourdomain`, for `InboundRecipient`.

## 3. WhatsApp (End User Messaging Social)
1. Console > End User Messaging Social > Add WhatsApp account. Sign in to Meta and link/create the WhatsApp Business Account.
2. Add a phone number (must not already be on WhatsApp). Copy its `phone-number-id-...`.
3. In Meta WhatsApp Manager > Message templates > create a Utility template, e.g. `payee_change_verification`:
   body with one variable `{{1}}`, and two Quick Reply buttons ("Yes, we authorised", "No, we did NOT").
4. Add your own phone as a test recipient.

## 4. SMS (End User Messaging SMS)
Create/choose an origination identity for your destination country. India needs DLT registration; if that is not ready,
leave SMS as the fallback path and demo WhatsApp as the primary path.

## 5. Build and deploy
```bash
sam build
sam deploy --guided --capabilities CAPABILITY_IAM \
  --parameter-overrides SesFromAddress=guardian@mail.yourdomain ApproverEmail=you@yourdomain \
    WhatsAppOriginationId=phone-number-id-XXXX WhatsAppTemplate=payee_change_verification \
    SmsOriginationIdentity=+1XXXXXXXXXX InboundRecipient=vendor-updates@mail.yourdomain
```
Note the stack outputs: `DashboardUrl`, `WhatsAppInboundTopicArn`, `SmsInboundTopicArn`, `VendorsTable`.

## 6. Wire up and seed
1. Activate the receipt rule set: SES > Email receiving > Rule sets > select the stack's set > Set as active.
2. WhatsApp account > Event destination > the `WhatsAppInboundTopicArn`.
3. SMS origination identity > Two-way SMS > SNS topic = `SmsInboundTopicArn`.
4. Seed vendors with your test phone:
```bash
VENDORS_TABLE=<VendorsTable> DEMO_PHONE=+91XXXXXXXXXX APPROVER_EMAIL=you@yourdomain python3 scripts/seed_vendors.py
```

## 7. Dry run
1. Open `DashboardUrl`, press **Attack**. Your phone should get the WhatsApp message.
2. Tap **No**. The case should show BLOCKED and the approver should get an SES email.
3. Press **Legitimate**, tap **Yes**. The case should show APPROVED.
4. Send a real email to the inbound address with a bank change to test the SES path.
5. Check CloudWatch Logs for each Lambda if anything stalls.

## 8. Before you push the repo
```bash
git init && git add -A && git status        # confirm no .env, keys or samconfig.toml are staged
# optionally: git secrets --scan
```
