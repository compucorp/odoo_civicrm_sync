## Odoo CiviCRM integration: (Odoo module read-me)

### Overview:

This Odoo module provides CiviCRM (https://www.civicrm.org) and Odoo (https://www.odoo.com/) integration for contacts/partners and accounting.

### Scope:

The scope of the extension and module together allows for:

1. One way synchronisation of CiviCRM Contacts to Odoo Partners
2. One way synchronisation of CiviCRM Contributions to Odoo Invoices
3. Two way synchronisation of CiviCRM “financial transactions” to Odoo Payments

This extension requires a companion module to be installed on your CiviCRM system which can be found here: https://github.com/compucorp/uk.co.compucorp.odoosync.

This Odoo module component of this pair provides functionality to:

1. Listens for inbound sync of contacts from CiviCRM to create Partners.
2. Listens for inbound sync of contributions from CiviCRM to create Invoices and Invoice lines.
3. Listens for changes in the status of contributions and financial transactions to create payments in Odoo.
4. Syncs payments back to CiviCRM.

### Functionality:

This extension:

- Adds new fields to Partners, Invoices, Invoice lines and Payments to track changes in Odoo and links to CiviCRM entities.
- Adds a new scheduled action then runs periodically to push data from CiviCRM to Odoo.
- Listens for inbound sync of contacts and contributions from CiviCRM and processes them to create partners, invoices and invoices lines (or to update invoices or invoices lines as per the specification)

A more detailed specification can be found here:
https://compucorp.atlassian.net/wiki/spaces/PS/pages/258801754/Odoo+CiviCRM+Sync+Specifications

The system handles all use cases for changes to CiviCRM contributions including editing contributions which have been previously synced, although note that in that case due to the fact that an Odoo invoice cannot be edited, the system will create a technical refund for an invoice in Odoo and create a new invoice with the updated details. For more details of how this works please see [here](https://api.media.atlassian.com/file/75c13a37-7c50-4686-ade7-82e8a8ef5970/binary?token=eyJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJkZDgwOTRhOS04MWRjLTQzY2EtYWM2MS0xMWY4MzRjYjZjMjUiLCJhY2Nlc3MiOnsidXJuOmZpbGVzdG9yZTpmaWxlOjc1YzEzYTM3LTdjNTAtNDY4Ni1hZGU3LTgyZThhOGVmNTk3MCI6WyJyZWFkIl19LCJleHAiOjE2MTIyOTU3NDksIm5iZiI6MTYxMjIxMjc2OX0.d45CLhL9sznbBYJFLPdsgLcORvUY3v_fUCOlI3peEa0&client=dd8094a9-81dc-43ca-ac61-11f834cb6c25&name=CiviCRM%20to%20Odoo%20Contribution%20Sync.png&max-age=2940&width=1648&height=2479).

### Setup:

CiviCRM Sync configuration can be configured by going to Administer -> General Settings -> CiviCRM Sync

All CiviCRM Sync settings must be configured in order for the sync to work. 

- CiviCRM Instance URL:  [CiviCRM REST interface](https://docs.civicrm.org/dev/en/latest/api/interfaces/#rest) 
- CiviCRM Site key: [CiviCRM Site key](https://docs.civicrm.org/dev/en/latest/api/interfaces/#keys)
- CiviCRM API key: [CiviCRM API Key](https://docs.civicrm.org/dev/en/latest/api/interfaces/#keys)
- Batch Size: No of contacts / contributions to sync in one time
- Retry Threshold: Number of attempts to sync 
- Error Notice Address: The email address that the system will send email to when the sync contains errors.


![screenshot-ase-odoo local_8069-2021 02 02-08_49_23](https://user-images.githubusercontent.com/208713/106576109-b38d0380-6534-11eb-9abd-611debbe4936.png)


### Guidance and limitations:

Please note:

1. In the current phase, Odoo CiviCRM Sync only supports single company Odoo setup.
2. The Sync does not modify Odoo or CiviCRM chart of accounts, it is the user's own responsibility to make sure the required chart of accounts is created correctly in both environments.
3. The Sync does not modify Odoo Taxes or CiviCRM Financial Types, it is the user's own responsibility to make sure the required tax account is created in CiviCRM and matched with Tax type with same name in Odoo.
4. The Sync does not modify Odoo Journals or CiviCRM Financial Types, it is the user's own responsibility to make sure the required financial account is created in CiviCRM and matched with Journal with same name in Odoo.
5. The Sync does not modify Odoo Partner Title list or CiviCRM Contact prefix list, it is the user's own responsibility to make sure the required titles are created in Odoo and matched with contact prefix in CiviCRM.
6. All taxes are not included in the price since CiviCRM's price is not tax inclusive.
