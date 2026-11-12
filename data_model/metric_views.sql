-- Unity Catalog metric views on the fallback data. ${catalog} and ${prefix} (the schema prefix from
-- lab.yaml) are filled by build_ddl.py.
-- Statements are separated by a line containing only $$; so build_ddl.py can run them one at a time.
-- YAML lists use flow mappings: the workspace metric view parser rejects block sequences after the first item.

CREATE OR REPLACE VIEW ${catalog}.${prefix}rights.license_metrics
WITH METRICS
LANGUAGE YAML
AS $$
version: 1.1
source: ${catalog}.${prefix}rights.license_agreement
comment: "Hoshi Stream license agreements by licensor, type, status and territory scope."
joins:
  - {name: licensor, source: "${catalog}.${prefix}rights.holder", 'on': "source.primary_license_holder_id = licensor.holder_id"}
dimensions:
  - {name: Licensor, expr: "licensor.rights_holder_name"}
  - {name: Agreement Type, expr: "agreement_type"}
  - {name: Agreement Status, expr: "agreement_status"}
  - {name: Territory Scope, expr: "territory_scope"}
  - {name: Expiry Month, expr: "DATE_TRUNC('MONTH', expiry_date)"}
  - {name: Agreement Number, expr: "agreement_number"}
measures:
  - {name: Agreement Count, expr: "COUNT(1)"}
  - {name: Active Agreement Count, expr: "SUM(CASE WHEN agreement_status = 'Active' THEN 1 ELSE 0 END)"}
  - {name: Minimum Guarantee Total, expr: "SUM(minimum_guarantee_amount)"}
  - {name: Total License Fee, expr: "SUM(total_license_fee)"}
  - {name: Average Royalty Percentage, expr: "AVG(royalty_percentage)"}
$$;

CREATE OR REPLACE VIEW ${catalog}.${prefix}sales.ad_delivery_metrics
WITH METRICS
LANGUAGE YAML
AS $$
version: 1.1
source: ${catalog}.${prefix}sales.impression_delivery
comment: "Hoshi Stream free-tier ad impressions by advertiser, campaign objective and month. One row is one served ad impression."
joins:
  - {name: campaign, source: "${catalog}.${prefix}sales.campaign", 'on': "source.campaign_id = campaign.campaign_id", joins: [{name: advertiser, source: "${catalog}.${prefix}sales.advertiser", 'on': "campaign.advertiser_id = advertiser.advertiser_id"}]}
dimensions:
  - {name: Advertiser, expr: "campaign.advertiser.trade_name"}
  - {name: Campaign Objective, expr: "campaign.campaign_type"}
  - {name: Campaign, expr: "campaign.name"}
  - {name: Delivery Month, expr: "DATE_TRUNC('MONTH', delivery_date)"}
  - {name: Insertion Type, expr: "insertion_type"}
  - {name: Verification Status, expr: "verification_status"}
measures:
  - {name: Impressions Delivered, expr: "SUM(total_impressions_served)"}
  - {name: Viewable Impressions, expr: "SUM(viewable_impressions)"}
  - {name: Viewability Rate, expr: "SUM(viewable_impressions) / SUM(total_impressions_served)"}
  - {name: Completed Views, expr: "SUM(completed_views)"}
  - {name: Average CPM, expr: "AVG(cpm_realized)"}
$$;
