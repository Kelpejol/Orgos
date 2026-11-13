# Teams approval cards: greyed out once decided, and a daily list of what is waiting

For whoever maintains the Power Automate flows. Decided with Compliance on 13 November 2026.

Teams keeps chat messages in the order they were sent, and nothing can reorder them. So:

1. When a document is decided, its card is **replaced** by a greyed card with no button, which says what happened ("Approved by Jane Okafor on 13 Nov 2026").
2. Every morning, one short card lists only the documents **still waiting** for that approver. It is the newest message, so what is waiting is always at the bottom of the chat.

## 1. Columns on the Document Lifecycle list

Add them with `python scripts/provision_sharepoint_columns.py --list "Document Lifecycle" --apply`. All four are single lines of text.

| Column | Written by | What it holds |
|---|---|---|
| `ApproveUrl` | OrgOS, when a document is sent for approval | The link for the card's "Review & Decide" button |
| `DecisionSummary` | OrgOS, whenever something happens to the approval | The line the greyed card shows, e.g. "Approved by Jane Okafor on 13 Nov 2026", "Returned to Review by …", "Moved to … on …; no decision needed from you", "Recalled by the document owner …", "Approval reversed by …" |
| `TeamsMessageId` | Flow A | The ID of the card now in Teams; emptied by Flow B once the card is greyed |
| `TeamsCardFor` | Flow A | Who that card was sent to (the approver's Entra ID) |

OrgOS never writes `TeamsMessageId` or `TeamsCardFor`. The flows never write `ApproveUrl` or `DecisionSummary`.

## 2. Flow A: post the card

Change the existing approval-card flow. If it posts on a different trigger today, change the trigger to this one.

- **Trigger:** SharePoint, *When an item is created or modified*, on Document Lifecycle.
- **Trigger conditions** (Settings → Trigger conditions), all four:
  - `@equals(triggerOutputs()?['body/Stage']?['Value'], 'Approval')`
    (or `['body/Stage']` if Stage is a text column)
  - `@not(equals(triggerOutputs()?['body/ApprovalStatus'], 'Approved'))`
  - `@not(empty(triggerOutputs()?['body/ApproverEntraId']))`
  - `@empty(triggerOutputs()?['body/TeamsMessageId'])`
- **Post card in a chat or channel** (Post as: Flow bot; Post in: Chat with Flow bot; Recipient: the approver's email). The card's "Review & Decide" button is an `Action.OpenUrl` to `ApproveUrl`.
- **Update item** on Document Lifecycle, same ID:
  - `TeamsMessageId` = the post action's *Message ID*
  - `TeamsCardFor` = `ApproverEntraId`

The last condition means a new card is posted only after the old one has been greyed (Flow B empties `TeamsMessageId`). So when the approver changes, the old approver's card is greyed first, then the new approver gets a card.

## 3. Flow B: grey the card out

- **Trigger:** SharePoint, *When an item is created or modified*, on Document Lifecycle.
- **Trigger conditions:**
  - `@not(empty(triggerOutputs()?['body/TeamsMessageId']))`
  - and any one of these (one condition, using `or`):
    `@or(equals(triggerOutputs()?['body/ApprovalStatus'], 'Approved'), equals(triggerOutputs()?['body/ApprovalStatus'], 'Rejected'), not(equals(triggerOutputs()?['body/Stage']?['Value'], 'Approval')), not(equals(triggerOutputs()?['body/TeamsCardFor'], triggerOutputs()?['body/ApproverEntraId'])))`
- **Update an adaptive card in a chat or channel**: Post as Flow bot, the same recipient as Flow A, Message ID = `TeamsMessageId`, and this card:

```json
{
  "type": "AdaptiveCard",
  "version": "1.4",
  "body": [
    { "type": "TextBlock", "text": "@{triggerOutputs()?['body/Title']}", "weight": "Bolder", "wrap": true, "isSubtle": true },
    { "type": "TextBlock", "text": "✓ @{triggerOutputs()?['body/DecisionSummary']}", "wrap": true, "isSubtle": true, "spacing": "Small" }
  ]
}
```

  It has no actions, so there is no button left to press.
- **Update item**, same ID: `TeamsMessageId` = empty, `TeamsCardFor` = empty.

## 4. Flow C: the daily list of what is waiting

- **Trigger:** Recurrence, every weekday at 08:30 (Africa/Lagos).
- **Get items** on Document Lifecycle, Filter Query: `Stage eq 'Approval' and ApprovalStatus ne 'Approved'`.
- Group the items by approver (the `Approver` person column's email). For each approver with at least one item, **Post card in a chat or channel** to that approver:

```json
{
  "type": "AdaptiveCard",
  "version": "1.4",
  "body": [
    { "type": "TextBlock", "text": "Still waiting for your decision", "weight": "Bolder" },
    { "type": "TextBlock", "text": "- [Context and Interested Parties Policy](https://…/lifecycle/approve/882) — since 10 Nov", "wrap": true }
  ]
}
```

  Build one line per item from `Title`, `ApproveUrl` and `SubmittedForApproval`.

Skip anyone with nothing waiting: no card means nothing is pending.

## 5. Checking it

1. Send a test document for approval. One card should arrive.
2. Approve it in OrgOS. Within a minute the card should turn grey, read "✓ Approved by … on …", and have no button.
3. Send another one, then use "Change approver" on its card. The first approver's card should turn grey with "Moved to …", and the new approver should get a card.
4. Leave one waiting overnight. The next morning's list should show only that one.

Opening an old link still works: the OrgOS approval page says the document is already approved or returned, and offers no decision.

The stakeholder feedback cards (Sensitisation) can be handled the same way later, if you want: the same columns pattern, with the feedback page as the link.
