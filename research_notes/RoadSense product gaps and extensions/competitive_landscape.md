# Competitive Landscape and Business Models: AI Road-Damage / Pavement-Condition Detection

Research date: 2026-11-12. Scope: 2024-2026 market state; older items are marked HISTORICAL. Many sources are vendor press releases or secondary aggregators (pulse.bot, cp.soar.com council-meeting summaries); these are flagged where relevant.

## Who are the main players and what does each offer (2025-2026)?

### Takeaway
The market has split into two camps. The first is **survey and asset-management vendors** (Vialytics, Cyvl, RoadAI/Xweather, Michelin/RoadBotics, Blyncsy/Bentley, StreetScan, Pavemetrics-based survey vehicles). They sell periodic network condition ratings to public-works and capital-planning staff. The second, newer camp is **fleet and connected-vehicle data players** (Samsara Ground Intelligence, Waymo+Waze, Nexar). Since 2026 they have pushed near-real-time pothole feeds to cities, often for free or bundled into products cities already pay for. No vendor found closes the loop by filing verified, deduplicated, human-approved reports into 311 work-order systems, which is RoadSense's core.

### Cited Findings
**Michelin Mobility Intelligence (formerly RoadBotics)**
- Michelin acquired Pittsburgh-based RoadBotics, which specialises in AI analysis of road images collected mainly by smartphone cameras. The aim was to consolidate Michelin's data-intelligence offer and speed up its Michelin DDi "Safer Roads" solution in North America, and later in Europe. — [Automotive World](https://www.automotiveworld.com/news/michelin-acquires-roadbotics-a-start-up-specialized-in-road-infrastructure-computer-vision/); [TRAC Canada](https://tracanada.ca/industry-news/michelin-acquires-roadbotics)
- Michelin Mobility Intelligence now markets a "Better Roads" offering, and the pavement AI is branded RoadWay at roadbotics.com. — [Michelin Mobility Intelligence](https://mobilitydata.michelin.com/our-publishers/michelin-ddi)
- Michelin's SCAPA presentation describes the workflow: a smartphone mounted on the windshield collects data while a route is driven, and results appear online about 30-45 days later. — [Michelin MMI SCAPA presentation (PDF)](https://assets.noviams.com/novi-file-uploads/scapa/pdfs-and-documents/ai___michelin_mobility_intelligence_platform_-_better_roads_-_scapa_presentation__shared__-_neil.pdf)
- CB Insights claims RoadBotics raised $20M in 2025. This conflicts with its acquired status and is unverified. — [CB Insights](https://www.cbinsights.com/company/roadbotics/alternatives-competitors)

**Vialytics (Germany; expanding fast in the US)**
- Smartphones mounted in city vehicles continuously capture and analyse pavement data with AI. Hartford, CT adopted it citywide in June 2025. — [finanzen.net / press release](https://www.finanzen.net/nachricht/aktien/city-of-hartford-takes-bold-step-toward-safer-more-data-driven-streets-with-vialytics-14568590)
- Launched AI detection of damaged lane markings to help cities prioritise repainting. — [Vialytics press release (mynewsdesk)](https://www.mynewsdesk.com/de/vialytics/pressreleases/vialytics-launches-ai-detection-for-damaged-lane-markings-to-help-cities-prioritize-repainting-3435363)
- Runs a "U.S. RoadStar Award" program (2025) for customer municipalities, a community and marketing play. — [Tullahoma News](https://www.tullahomanews.com/?p=104026)
- Sells through engineering-consultancy channels, e.g. Elkton, MD via Verdantas (35-mile network), plus a strategic partnership with BETA. — [PR Newswire](https://prnewswire.com/news-releases/vialytics-and-beta-forge-strategic-partnership-to-advance-infrastructure-innovation-302359732.html); [Silicon Canals / search summary](https://siliconcanals.com/vialytics-bags-9-2m/)
- Funding reports conflict: CB Insights lists a Series A-II of $8.4M on 2024-12-18, while Dealroom cites a $10M Series A in January 2023 led by Scania Growth Capital. — [CB Insights](https://www.cbinsights.com/company/vialytics/financials); [Dealroom](https://dealroom.co/companies/vialytics/)
- Alexandria, VA's federally funded SMART Roadway pilot selected Vialytics and Vaisala as vendors, with Phase 1 launched in August 2025. — [Alexandria](https://alexandriava.gov/go/7263); [Alexandria USDOT SmartScan PDF](https://www.alexandriava.gov/sites/default/files/2025-12/USDOTSmartScan.pdf)

**Cyvl (Somerville, MA)**
- Uses AI plus vehicle-mounted LiDAR. Raised a $14M Series A led by Sentinel Global (announced 2025-10-01; PitchBook/WPI list 2025-08-07). Total funding is about $22.7-23.7M. — [Business Wire](https://www.businesswire.com/news/home/20251001717298/en); [Axios Pro](https://www.axios.com/pro/enterprise-software-deals/2025/10/01/cyvl-14-million-series-a-city-planning); [CB Insights](https://www.cbinsights.com/company/cyvlai/financials)
- Detects potholes and sidewalk cracks and pitches itself as an "infrastructure intelligence layer". — [Tech Brew](https://www.techbrew.com/stories/2025/10/06/cyvl-ai-potholes-sidewalk-cracks); [technologies.org](https://technologies.org/cyvl-raises-14m-to-build-the-infrastructure-intelligence-layer-for-america/)
- Buffalo, NY deployed Cyvl's AI-LiDAR platform for road prioritisation (price not disclosed). — [Kurrant](https://kurrant.com/kurrantly-news/buffalo-deploys-ai-lidar-platform-to-overhaul-road-prioritization-with-cyvl/); [SmartCitiesWorld](https://www.smartcitiesworld.net/news/buffalo-to-take-data-driven-approach-to-roadway-repairs-12744)

**Blyncsy (Bentley Systems): Payver**
- Bentley acquired Blyncsy (reported August 2023, HISTORICAL). — [Geo Week News](https://www.geoweeknews.com/articles/bentley-systems-blyncsy-infrastructure-ai-machine-learning/)
- Uses dashcam imagery, including crowdsourced and third-party footage ("roadway intelligence without the fieldwork"). It issues PASER ratings and detects potholes, cracking and paint lines. — [Carahsoft/Bentley](https://www.carahsoft.com/bentley/solutions/blyncsy); [Carahsoft blog 2026](https://www.carahsoft.com/blog/blyncsy-revolutionizing-road-safety-blog-2026); [Blyncsy Payver Pavement](https://blyncsy.com/payver/pavement/)
- Customers include Hawaii DOT ("Eyes on the Road": near-real-time issue reporting, with a vendor-claimed 95% cut in manual surveys) and Michigan DOT (multi-year contract for MIRE/HPMS roadway-characteristic data). Utah DOT ran a Payver pilot over 350+ road miles, and the Port Authority of NY & NJ also uses it. — [Bentley news (Hawaii)](https://www.bentley.com/news/hawaii-department-of-transportation-creates-safer-roads-with-bentley-systems-asset-analytics-solution/); [Roads & Bridges](https://roadsbridges.com/technology/article/55343844/how-blyncsys-ai-dashcam-technology-is-transforming-roadway-inspections); [TechCrunch (Utah)](https://techcrunch.com/?p=2158102); [ENR](https://www.enr.com/articles/62519-cameras-ai-and-sensors-bring-new-tools-for-road-inspection)
- Sold to government through Carahsoft, a federal/state reseller channel. — [Carahsoft](https://www.carahsoft.com/bentley/solutions/blyncsy)

**RoadAI (Vaisala, now under the Xweather brand)**
- Smartphone-video pavement and asset survey run in the cloud. Montreal's engineer reports results within 48 hours. Users include the Region of Waterloo, Montreal, Milton Keynes, Northumberland County and Suffolk. — [Xweather RoadAI x Montreal](https://www.xweather.com/blog/article/roadai-x-montreal); [Xweather x Waterloo](https://xweather.com/blog/article/roadai-x-region-of-waterloo); [Xweather x Milton Keynes](https://www.xweather.com/blog/article/roadai-x-milton-keynes)
- Vendor claim: up to 4x faster and half the price of a manual survey. — [Vaisala Road Asset Management](https://www.vaisala.com/products/road-asset-management)
- The UK G-Cloud listing offers unlimited devices and users, with results within hours of upload. — [UK Digital Marketplace](https://www.applytosupply.digitalmarketplace.service.gov.uk/g-cloud/services/581776053828682)
- Published a comparison of smartphone AI against an LCMS laser survey with the Danish road directorate. — [Xweather / Vejdirektoratet](https://www.xweather.com/customers/vejdirektoratet-roadai-smartphone-ai-versus-lcms)

**Pavemetrics (Eddyfi Technologies): LCMS-2**
- Single-pass 3D laser sensor that measures cracking, rutting, texture, potholes, bleeding, shoving, raveling and roughness. It is sold to integrators (e.g. ROMDAS) who build survey vehicles, and is the high-accuracy "gold standard" tier used in DOT and city surveys such as Cincinnati 2025. — [Pavemetrics LCMS-2](https://www.pavemetrics.com/?p=1378); [ROMDAS LCMS](https://romdas.com/romdas-lcms.html); [Cincinnati 2025 Pavement Condition Survey](https://vendorselfservice.cincinnati-oh.gov/sites/dote/assets/Street%20Rehab%20Program/Cincinnati-2025-Results-of-Pavement-Condition-Survey-Final-Report.pdf)
- ROMDAS offers an LCMS-4M module with a "pay as you use" pricing option; no dollar figures are published. — [ROMDAS](https://romdas.com/romdas-lcms.html)

**StreetScan (Montreal-based)**
- Uses scooter-mounted and vehicle-mounted sensors for road and sidewalk condition. Claims assessments in 100+ North American communities; customers include the Township of Meaford, ON. — [Meaford Independent](https://themeafordindependent.ca/?p=25222)

**Roadly, Inc.**
- Roadly PRO is an iPhone-as-dashcam app whose AI computes PCI. It targets municipal/state DOTs, construction firms and citizens. A separate free Roadly smart dashcam navigation app claims 900k+ users and sends road events to a crowdsourcing database. No funding or customer data was found. — [App Store: Roadly PRO](https://apps.apple.com/us/app/id6476778274); [App Store: Roadly smart dashcam](https://apps.apple.com/gb/app/roadly-smart-dashcam/id1012927089)

**Samsara: Ground Intelligence (launched May 2026)**
- Uses cameras already installed in commercial trucks to map developing potholes on a dashboard. Cities can pull anonymised footage to verify citizen reports (downed signs, clogged sewers). Chicago is among the contracted cities. The roadmap includes graffiti, guardrails, low power lines and risky intersections. Launched at Go Beyond 2026. — [TechCrunch](https://techcrunch.com/2026/05/12/potholes-cost-cities-millions-samsara-using-ai-trucks-fix/); [Samsara engineering blog](https://www.samsara.com/blog/designing-ground-intelligence-giving-cities-a-real-time-view-of-every-pothole); [StateTech](https://statetechmagazine.com/article/2026/05/ai-powered-fleet-technology-helps-deliver-faster-more-responsive-public-services); [Briefs](https://www.briefs.co/?p=6721)
- Samsara says it trained its own model to detect multiple pothole types and estimate how fast they are deteriorating. — [TechCrunch](https://techcrunch.com/2026/05/12/ai-is-turning-connected-cars-into-pothole-finding-machines/)

**Waymo + Waze (April 2026 pilot)**
- Waymo robotaxi-detected potholes are shared with city and state DOTs through the free Waze for Cities platform, alongside user reports. Waze drivers get alerts and can verify hazards. Initial markets are San Francisco, LA, Phoenix, Austin and Atlanta, with about 500 potholes identified (per aggregator). — [TechCrunch](https://techcrunch.com/2026/04/09/waymo-robotaxis-are-tracking-potholes-and-sharing-that-data-with-waze-users); [CBS News Texas](https://www.cbsnews.com/texas/news/waymo-waze-pothole-data-sharing-4-13-2026); [ABC7](https://abc7news.com/post/waymo-partners-waze-app-pothole-mapping-bay-area-help-city-crews-prioritize-repairs/18864412/)

**Nexar: CityStream**
- Dashcam network of 700k+ vehicles that Nexar says covers 94% of US roads monthly. CityStream Live detects work zones, sign changes, potholes and parking, with access via platform or API (e.g. into Esri). Nexar earlier ran a free program for public agencies, focused on work zones. — [GPS World](https://www.gpsworld.com/nexar-releases-citystream-live-a-real-time-mapping-platform-for-mobility/); [Nexar for cities](https://data.getnexar.com/solution/cities); [PR Newswire (free program)](https://www.prnewswire.com/il/news-releases/ahead-of-massive-infrastructure-bill-nexar-provides-cities-with-free-smart-city-technology-to-plan-road-improvements-301357904.html)

**Hayden AI**
- Bus-mounted AI cameras for bus-lane and bus-stop parking enforcement (NYC MTA, DC Metro, LA Metro, SEPTA, Sacramento). No pothole or pavement product was found. It is an adjacent "transit-fleet camera" player, not a direct competitor. — [Tech Brew](https://www.techbrew.com/stories/2024/09/19/hayden-ai-public-transit-mta-nyc); [Hayden AI fact sheet](https://www.hayden.ai/downloads/hai-bus-lane-fact-sheet.pdf); [IoT World Today](https://iotworldtoday.com/transportation-logistics/ai-powered-cameras-deployed-to-catch-parking-violations-at-bus-stops)

**Citizen 311 apps: SeeClickFix / CivicPlus 311 CRM**
- CivicPlus 311 CRM (formerly SeeClickFix) offers structured forms, GIS mapping, duplicate detection/merging and automated assignment. Its AI features include category search and photo analysis that suggests a request category. — [CivicPlus unified platform](https://www.civicplus.com/seeclickfix-311-crm/unified-platform/); [CivicPlus blog](https://www.civicplus.com/blog/crm/is-your-legacy-311-process-working-against-you/)
- Recent deployments: Charles County, MD (October 2025; warns users about existing reports) and Muskegon, MI (2025). — [Southern Maryland Chronicle](https://southernmarylandchronicle.com/2025/10/09/charles-debuts-mobile-reporting-system/); [Muskegon](https://muskegon-mi.gov/seeclickfix-to-streamline-non-emergency-reporting/)

**Others seen**
- Road Management Technologies / Roadway Management Technologies: laser/vehicle survey contracts in Auburn, AL and Lakeland, FL. — [cp.soar.com (Auburn)](https://cp.soar.com/articles/7035601/Auburn/Lee-County/Alabama/Auburn-council-approves-pavement-assessment-contract-equipment-and-infrastructure-contracts); [WUSF (Lakeland)](https://www.wusf.org/transportation/2026-01-05/lakeland-turns-to-ai-spot-potholes-road-cracks-sooner)
- CivicScan (Seattle, UW grads): AI platform that scans for pavement defects (2025). — [GeekWire](https://www.geekwire.com/2025/eyes-and-ai-on-the-road-uw-grads-platform-scans-for-pavement-defects-to-speed-repair-lower-costs/)
- San Jose's AI Road Safety Conditions Pilot (since 2023) reported 97% correct pothole identification and is being expanded. — [GovTech](https://www.govtech.com/artificial-intelligence/ai-helps-san-jose-calif-identify-potholes-and-obstacles)

### Inferences
- The incumbents' product is a **condition report or PCI map for capital planning**. The 2026 entrants (Samsara, Waymo/Waze) are pushing toward **real-time defect feeds for operations**. RoadSense sits on the operations side, closest to Samsara and Waze for Cities but with a human-approval and 311-filing workflow neither appears to offer.
- Big fleet and data players giving away or bundling pothole data (Waze for Cities is free; Samsara bundles it with fleets cities already run) threatens any "sell detections" model. Value will move to verification, deduplication, triage, routing and integration.

### Gaps
- Exact RoadBotics acquisition year (widely reported as 2022 but not confirmed by the sources retrieved), current Michelin RoadWay pricing, and whether the 2025 $20M CB Insights funding figure is real.
- No public detail on iPavement found. Roadly's funding and customers are unknown.
- Full list of Samsara Ground Intelligence city customers and pricing was not found.

## How do they capture data, and what outputs do they deliver?

### Takeaway
Capture methods range from a **$0 marginal-cost smartphone on the windshield** (Vialytics, RoadAI, RoadBotics/Michelin, Roadly) to **dashcam and connected-fleet video** (Blyncsy, Nexar, Samsara), **robotaxi sensors** (Waymo), **LiDAR vans** (Cyvl) and **3D laser survey vehicles** (Pavemetrics LCMS). Outputs are mostly PCI/PASER ratings, defect maps, asset inventories (signs, markings) and GIS/Esri exports. Real-time alerts are newer. Work-order creation is rare and appears only indirectly (e.g. Hawaii DOT reporting).

### Cited Findings
- Smartphone in a city vehicle: Vialytics (Hartford), RoadAI (Montreal, 48-hour turnaround), Michelin RoadWay (30-45 days to results). — [finanzen.net](https://www.finanzen.net/nachricht/aktien/city-of-hartford-takes-bold-step-toward-safer-more-data-driven-streets-with-vialytics-14568590); [Xweather Montreal](https://www.xweather.com/blog/article/roadai-x-montreal); [Michelin SCAPA PDF](https://assets.noviams.com/novi-file-uploads/scapa/pdfs-and-documents/ai___michelin_mobility_intelligence_platform_-_better_roads_-_scapa_presentation__shared__-_neil.pdf)
- Dashcam imagery analysed without a dedicated survey, producing PASER scores: Blyncsy. Hawaii DOT gets near-real-time issue identification and reporting. — [Carahsoft blog](https://www.carahsoft.com/blog/blyncsy-revolutionizing-road-safety-blog-2026); [Bentley (Hawaii)](https://www.bentley.com/news/hawaii-department-of-transportation-creates-safer-roads-with-bentley-systems-asset-analytics-solution/)
- Federal reporting outputs: Blyncsy provides MIRE/HPMS roadway-characteristic data to Michigan DOT. — [Roads & Bridges](https://roadsbridges.com/technology/article/55343844/how-blyncsys-ai-dashcam-technology-is-transforming-roadway-inspections)
- Connected-fleet cameras feeding a pothole map dashboard plus footage retrieval: Samsara. — [TechCrunch](https://techcrunch.com/2026/05/12/potholes-cost-cities-millions-samsara-using-ai-trucks-fix/)
- Crowdsourced dashcam network with API/Esri delivery: Nexar. — [GPS World](https://www.gpsworld.com/nexar-releases-citystream-live-a-real-time-mapping-platform-for-mobility/)
- AV sensor data delivered to cities through the Waze for Cities platform, with crowd verification by Waze users: Waymo. — [TechCrunch](https://techcrunch.com/2026/04/09/waymo-robotaxis-are-tracking-potholes-and-sharing-that-data-with-waze-users)
- LiDAR plus AI: Cyvl. 3D laser sensor (cracking, rutting, roughness, potholes): Pavemetrics LCMS-2. — [Tech Brew](https://www.techbrew.com/stories/2025/10/06/cyvl-ai-potholes-sidewalk-cracks); [Pavemetrics](https://www.pavemetrics.com/?p=1378)
- Scooter- and vehicle-mounted sensors for sidewalks and roads: StreetScan. — [Meaford Independent](https://themeafordindependent.ca/?p=25222)
- Lane-marking degradation detection as an add-on output: Vialytics. — [mynewsdesk](https://www.mynewsdesk.com/de/vialytics/pressreleases/vialytics-launches-ai-detection-for-damaged-lane-markings-to-help-cities-prioritize-repainting-3435363)
- Repurposed-smartphone camera for road hazards and pavement distress: CityROVER (Visual Defence, Canada). — [IRCAI Top 100](https://ircai.org/top100/entry/sustainable-infrastructure-management-using-cityrover-ai/)
- Pothole deterioration-rate estimation: Samsara. — [TechCrunch](https://techcrunch.com/2026/05/12/ai-is-turning-connected-cars-into-pothole-finding-machines/)

### Inferences
- RoadSense's on-device YOLO with privacy blurring before upload is a differentiator against cloud-upload smartphone workflows (Vialytics, RoadAI, Michelin), which send raw video to the cloud. This matters for Canadian privacy law (PIPEDA and provincial FOIPOP) but is not something competitors publicise.
- No surveyed competitor advertises native Open311/311-CRM ticket creation with human approval. Integration is mostly GIS/Esri export or a dashboard.
- To be taken seriously by public-works asset managers, RoadSense likely needs a PCI/PASER-style condition output in addition to discrete pothole tickets.

### Gaps
- Whether Vialytics, Cyvl or RoadAI offer direct integrations into 311 CRMs (CivicPlus, Salesforce, Cityworks). The sources reviewed do not say.

## What pricing and business models are used? Any public contract values?

### Takeaway
Small and mid-sized municipalities buy **annual SaaS subscriptions plus a setup fee**. Vialytics public figures cluster at **about US$4.3k-14.6k per year**, with multi-year terms. Traditional vehicle surveys run **tens of thousands to hundreds of thousands per cycle** (e.g. HRM's 2024 high-speed survey at CA$225k). State DOTs buy multi-year analytics contracts through resellers (Blyncsy via Carahsoft). Fleet and data players (Samsara, Nexar, Waze) monetise through **bundling, data licensing or free civic programs**. No source found published per-lane-km pricing for AI smartphone products.

### Cited Findings
- **Vialytics, Thorpe borough, PA:** $475 setup/implementation/support plus a $4,320 one-year subscription = $4,795 first year. — [Times News (tnonline)](https://www.tnonline.com/?p=282076)
- **Vialytics, Pennsylvania council (likely Lower Burrell):** five-year agreement at $11,520 per year plus a $2,875 setup fee. — [TribLive](https://mirror.triblive.com/local/valley-news-dispatch/artificial-intelligence-to-help-lower-burrell-public-works-save-money-plan-road-repairs)
- **Vialytics, Canonsburg, PA (April 2026):** about $10,000 initially, then about $8,300 per year. — [Observer-Reporter](https://www.observer-reporter.com/news/local-news/2026/apr/16/canonsburg-adopts-ai-tool-to-assess-road-condition/)
- **Vialytics, unnamed city:** $14,560 per year plus a $4,750 setup fee for a one-year trial. Franklin, IN board approved a three-year Vialytics asset-management contract (figure not captured). — [cp.soar.com (Franklin)](https://cpo.soar.com/articles/7699771/Franklin-City/Johnson-County/Indiana/Board-approves-three-year-asset-management-contract-with-Violytics-for-road-and-asset-inventory)
- **Road Management Technologies, Auburn, AL:** $74,448 annual pavement assessment with two one-year extension options. **Lakeland, FL:** four-year $240,000 contract with Roadway Management Technologies (January 2026). — [cp.soar.com (Auburn)](https://cp.soar.com/articles/7035601/Auburn/Lee-County/Alabama/Auburn-council-approves-pavement-assessment-contract-equipment-and-infrastructure-contracts); [WUSF](https://www.wusf.org/transportation/2026-01-05/lakeland-turns-to-ai-spot-potholes-road-cracks-sooner)
- **Minot, ND:** $167,000 pavement management contract, approved after debate over local alternatives. **Parker, TX:** $60,000 pavement condition study using LiDAR and machine learning. — [cp.soar.com (Minot)](https://cpo.soar.com/articles/7893842/Minot/Ward-County/North-Dakota/Council-approves-167000-pavement-management-contract-after-debate-on-local-alternatives); [cp.soar.com (Parker)](https://cpo.soar.com/articles/7640354/Parker/Collin-County/Texas/Council-authorizes-60000-pavement-condition-study-using-lidar-and-machine-learning)
- **HISTORICAL, RoadBotics, Savannah, GA (2018):** contract modification of $24,990 for roadway condition assessment. — [Savannah agenda](https://agenda.savannahga.gov/publishing/december-20-2018-city-council-regular-meeting/126_2972.html)
- **Halifax (HRM) baseline:** HRM rates roads on a two-year cycle with a high-speed pavement condition data collection unit. Tender HRM-2024-0046 (High Speed Pavement Condition Data Collection) went to Englobe for CA$225,002. — [Bidsfactory tender](https://bidsfactory.com/en/tenders/high-speed-pavement-condition-data-collection-nova_scotia_tenders-038b9523f6aa3568); [Halifax Paving & Repair](https://www.halifax.ca/transportation/streets-sidewalks/paving-repair)
- **RoadAI pricing model:** the G-Cloud listing offers unlimited devices and users, which suggests a flat subscription rather than per-seat pricing (no figures published). The 2021 TfL condition-survey award of £365k is unrelated to RoadAI. — [UK Digital Marketplace](https://www.applytosupply.digitalmarketplace.service.gov.uk/g-cloud/services/581776053828682); [Find a Tender](https://www.find-tender.service.gov.uk/Notice/028568-2021/PDF)
- **Free and bundled models:** Waze for Cities is free to use. Nexar earlier offered a free program to agencies. Samsara sells Ground Intelligence alongside its fleet telematics to cities. — [TechCrunch (Waymo/Waze)](https://techcrunch.com/2026/04/09/waymo-robotaxis-are-tracking-potholes-and-sharing-that-data-with-waze-users); [PR Newswire (Nexar)](https://www.prnewswire.com/il/news-releases/ahead-of-massive-infrastructure-bill-nexar-provides-cities-with-free-smart-city-technology-to-plan-road-improvements-301357904.html); [StateTech](https://statetechmagazine.com/article/2026/05/ai-powered-fleet-technology-helps-deliver-faster-more-responsive-public-services)
- **Channel models:** Bentley/Blyncsy sells via Carahsoft to government. Vialytics partners with engineering consultancies (Verdantas, BETA). Pavemetrics sells sensors to integrators (ROMDAS). — [Carahsoft](https://www.carahsoft.com/bentley/solutions/blyncsy); [PR Newswire (BETA)](https://prnewswire.com/news-releases/vialytics-and-beta-forge-strategic-partnership-to-advance-infrastructure-innovation-302359732.html); [ROMDAS](https://romdas.com/romdas-lcms.html)
- **Grant-funded pilots:** Alexandria, VA's SMART Roadway pilot is funded through a USDOT grant. — [Alexandria](https://alexandriava.gov/go/7263)

### Inferences
- Vialytics' public prices set the price anchor for a small-municipality AI road SaaS at roughly US$5k-15k per year. A CA$225k biennial vehicle survey (HRM) is the incumbent budget line that AI tools claim to undercut ("half the cost", per Vaisala).
- Business models RoadSense is not yet using: (1) annual SaaS with setup fee, tiered by network km; (2) selling through engineering consultancies; (3) grant-funded pilots (Canada's NRC IRAP and ISED, mirroring USDOT SMART grants); (4) data licensing or API to insurers, fleets and navigation apps; (5) bundling with fleet telematics; (6) a free tier for citizens and civic users with a paid municipal workflow layer.
- No source found for insurance-based business models (insurers paying for pothole data) in 2024-2026. Treat this as unvalidated.

### Gaps
- No per-lane-km pricing found for any AI vendor. No public Cyvl, Blyncsy, Samsara or Michelin contract values were found in 2024-2026 records.
- The Franklin, IN Vialytics contract amount was not captured.

## Any Canada- or Atlantic-Canada-specific players or deployments?

### Takeaway
Canada has active deployments: RoadAI in Montreal and Waterloo Region, StreetScan (Montreal-based) and irisGO (Owen Sound), Vaughan demonstration-zone pilots (GeoMate, ApoSys/RoadSight AI), CityROVER (Visual Defence), Calgary AI tests, and NRC-funded R&D. **Atlantic Canada is nearly empty.** The only lead is a 2022 (HISTORICAL) listing of Moncton as a CityROVER user. Halifax still relies on a traditional high-speed survey contract (Englobe, CA$225k, 2024). This gives RoadSense a local-first opening.

### Cited Findings
- RoadAI is used by Montreal and the Region of Waterloo. — [Xweather Montreal](https://www.xweather.com/blog/article/roadai-x-montreal); [Xweather Waterloo](https://xweather.com/blog/article/roadai-x-region-of-waterloo)
- StreetScan (Montreal) has partnered with the Township of Meaford and claims 100+ North American communities. — [Meaford Independent](https://themeafordindependent.ca/?p=25222)
- Owen Sound, ON uses irisGO AI devices in public-works vehicles to set resurfacing priorities. — [GovLaunch](https://govlaunch.com/governments/owen-sound-on/projects/owen-sound-on-informs-its-asphalt-resurfacing-plans-with-irisgo-road-evaluation-technology)
- Vaughan, ON tested GeoMate and ApoSys (RoadSight AI) for AI road asset inventory in its 2025 OVIN demonstration zone (June-November 2025). — [Vaughan GeoMate summary](https://vaughanbusiness.ca/wp-content/uploads/2026/03/GeoMate_Summary_Vaughan-TIP-OVIN-DZ-2025-accessible.pdf); [Vaughan ApoSys summary](https://vaughanbusiness.ca/wp-content/uploads/2026/03/ApoSys-Technologies_Summary_Vaughan-TIP-OVIN-DZ-2025-accessible.pdf)
- NRC funding: $100,000 (June 2025-March 2026) for AI tools that detect pavement and sidewalk defects from camera and LiDAR data, and a $36,000 pilot to CityScan Technologies for AI pavement assessment. — [Open Canada grant record](https://search.open.canada.ca/grants/record/nrc-cnrc%2C172-2025-2026-Q1-1031766%2Ccurrent); [Open Canada grant record 2](https://search.open.canada.ca/grants/record/nrc-cnrc%2C172-2024-2025-Q3-1024315%2Ccurrent)
- Calgary's initial tests suggested AI could detect defects better than humans, with varying accuracy. — [CBC Calgary](https://amp.cbc.ca/news/canada/calgary/ai-calgary-roadwork-potholes-1.7003767)
- University of Waterloo research on low-cost AI pothole detection. — [UWaterloo News](https://uwaterloo.ca/news/news/ai-system-makes-finding-potholes-cheaper-and-easier)
- HISTORICAL (2022): Moncton is listed as a CityROVER user (Visual Defence, repurposed smartphones). — [IRCAI](https://ircai.org/top100/entry/sustainable-infrastructure-management-using-cityrover-ai/); [CityROVER case study](https://www.cityrover.com/case-studies/town-of-the-blue-mountains-on/)
- Halifax: two-year condition survey cycle via a high-speed data collection unit, and a pavement management system used for capital planning. A council report proposes lowering the service target to "60% Good", letting the "Poor" backlog grow from 15% to 20% over ten years. HRM's Auditor General has also reviewed road and sidewalk asset management. — [Halifax Paving & Repair](https://www.halifax.ca/transportation/streets-sidewalks/paving-repair); [Halifax council report](https://cdn.halifax.ca/media/85049); [HRM Auditor General report](https://hrmauditorgeneral.ca/themes/user/site/default/asset/img/common/Roads_and_Sidewalks_FINAL_Web_Print_Version_June_25.pdf)
- Samsara has a Canadian-localised blog page for Ground Intelligence, suggesting Canadian market intent. — [Samsara CA blog](https://www.samsara.com/ca/blog/designing-ground-intelligence-giving-cities-a-real-time-view-of-every-pothole)

### Inferences
- A tighter HRM budget (lowering the "Good" target) points to cheaper, continuous, triage-focused monitoring rather than more expensive surveys. That is a fit for RoadSense's pitch.
- Bilingual (French) support would matter for expansion into New Brunswick and Quebec, where competitors such as StreetScan are already established.

### Gaps
- No evidence found of Vialytics, Cyvl, Blyncsy, Nexar or Samsara deployments in Atlantic Canada. St. John's, Charlottetown and Fredericton returned no results. The Fredericton company lead (Atlantic Business Magazine) could not be verified.
- Whether HRM's 311 system exposes an Open311 endpoint was not confirmed in this research.

## What gaps or complaints do customers report?

### Takeaway
There are few public complaints and no city pilot was found ending over accuracy. The recurring concerns are **accuracy and repeatability** (false positives, varying detection quality), the **need for manual validation and ground truth**, **slow turnaround** (Michelin at 30-45 days), **integration with city operations platforms**, and **local-alternative and cost debates** in councils. Duplicate citizen 311 reports are a known pain that 311 vendors address only with basic merging.

### Cited Findings
- Ohio DOT's first-phase test had accuracy problems ("something resembled a pothole but wasn't"). — [ENR](https://www.enr.com/articles/62519-cameras-ai-and-sensors-bring-new-tools-for-road-inspection)
- Calgary noted the AI outlined deformations "with varying degrees of accuracy". — [CBC Calgary](https://amp.cbc.ca/news/canada/calgary/ai-calgary-roadwork-potholes-1.7003767)
- A National Academies (TRB) synthesis says acceptance of AI results requires ground-truth testing and model validation. — [National Academies 27993](https://www.nationalacademies.org/read/27993/chapter/3)
- Danish road directorate commentary (via Xweather) says many AI tools fall short on basic repeatability, accuracy and robustness. — [Xweather / Vejdirektoratet](https://www.xweather.com/customers/vejdirektoratet-roadai-smartphone-ai-versus-lcms)
- NYC's bike-lane computer-vision pilot needed repeated cycles of manual validation and model adjustment. — [NYC Tech Testbed](https://testbed.cityofnewyork.us/assessing-bike-lane-conditions/)
- Alexandria's pilot is explicitly evaluating data accuracy, integration with city operational platforms, and scalability. — [Alexandria](https://alexandriava.gov/go/7263)
- Minot, ND's council debated local alternatives before approving a $167k pavement-management contract. — [cp.soar.com (Minot)](https://cpo.soar.com/articles/7893842/Minot/Ward-County/North-Dakota/Council-approves-167000-pavement-management-contract-after-debate-on-local-alternatives)
- Michelin RoadWay results take 30-45 days to appear. — [Michelin SCAPA PDF](https://assets.noviams.com/novi-file-uploads/scapa/pdfs-and-documents/ai___michelin_mobility_intelligence_platform_-_better_roads_-_scapa_presentation__shared__-_neil.pdf)
- Samsara's accuracy has not been independently verified (no public accuracy data found). — [TechCrunch](https://techcrunch.com/2026/05/12/ai-is-turning-connected-cars-into-pothole-finding-machines/)
- 311 vendors market duplicate merging (CivicPlus). A widely repeated "40% of pothole requests are duplicates" figure comes from a competing vendor's marketing and is unverified. — [CivicPlus](https://www.civicplus.com/seeclickfix-311-crm/unified-platform/); [OxMaint (vendor)](https://oxmaint.com/industries/government/municipal-pothole-repair-software-backlog-reduction-guide)
- Waze relies on crowd verification by users to improve the accuracy of Waymo-reported potholes, which acknowledges false-positive risk. — [TechCrunch](https://techcrunch.com/2026/04/09/waymo-robotaxis-are-tracking-potholes-and-sharing-that-data-with-waze-users)

### Inferences (white space RoadSense could own)
1. **The verified-to-ticket loop.** Competitors stop at a map, a dashboard or a PCI report. RoadSense's LLM-agent verification, deduplication against existing 311 tickets, triage, routing and human-approved Open311 filing turns detections into work orders. This addresses the accuracy and validation concerns above, since a human approves each report.
2. **Aggregator, not just detector.** With Waze for Cities (free), Samsara and Nexar feeds arriving, RoadSense could ingest third-party feeds plus citizen 311 reports and dedupe across all sources. That would make it the "single source of truth" layer on top of free data, rather than competing on detection.
3. **Privacy-by-design for Canada.** On-device blurring before upload is a differentiator against cloud-upload smartphone tools, and no competitor publicises it.
4. **Atlantic Canada, local-first.** No AI vendor is visibly deployed in Halifax or the Atlantic provinces, and HRM's survey budget (CA$225k per cycle) and service-level pressure create an opening.
5. **Features RoadSense lacks relative to the market:** PCI/PASER network condition scoring; asset inventory (signs, lane markings, sidewalks; Vialytics and Blyncsy have these); deterioration tracking over time (Samsara); GIS/Esri export and asset-management integration (Cityworks and similar); capital-planning and budget scenario tools; footage retrieval for verifying citizen reports (Samsara); support for municipal-fleet, transit or garbage-truck mounting; winter-specific defects (frost heave, plowing damage); French language; accuracy benchmarking against LCMS (the RoadAI/Vejdirektoratet approach).
6. **Business models to add:** per-km annual SaaS plus setup (US$5k-15k anchor for small towns); a consultancy channel; NRC IRAP and grant-funded pilots; data licensing or API to insurers and navigation apps (unvalidated); a free citizen dashcam app feeding a paid municipal tier (the Roadly and Nexar playbook).

### Gaps
- No user-review sites (G2, Capterra) or forums with substantive customer complaints about Vialytics, Cyvl, RoadAI or Blyncsy were found. Complaint evidence is thin and mostly comes from pilot reports.
- No independent head-to-head accuracy benchmark across vendors was found (only vendor-published comparisons).
