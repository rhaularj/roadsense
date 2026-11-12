# Technology Options for Extending RoadSense (state of the art 2024-2026)

Scope note: research done in a budget of about 17 search/fetch calls. Most figures come from search-result summaries of primary papers (arXiv, PMC, TRID). The RoadBench paper was fetched in full. Numbers marked "secondary" come from review blogs or aggregators and should be checked before use in decisions.

## Detection: best current models and datasets (RDD2022, CRDDC/ORDDC, YOLOv8-v11, RT-DETR, segmentation, winter/night, Canadian data)

### Takeaway
Road-damage detection on RDD2022 has levelled off at about 0.70-0.79 F1 for challenge-grade solutions. The best results come from YOLO ensembles, not from a single new architecture. Papers built on YOLO11 report gains of only +2-3 mAP points over stock YOLO11. No public Canadian dataset combines damage labels with snow or night imagery. The nearest is ViSnow (Montreal), which labels snow cover, not damage. RoadSense's biggest accuracy gain is therefore likely to come from local Halifax winter data, not from switching models.

### Cited Findings
- CRDDC'2022 (IEEE BigData): the winning solution was an ensemble of YOLO and Faster-RCNN models, scoring about 76% F1 on test data pooled from all 6 countries. The overview paper covers the top 11 solutions. Sources disagree on how many teams entered (more than 60 from 19 countries, or 121). — [CRDDC-2022 overview, arXiv 2211.11362](https://arxiv.org/abs/2211.11362v1)
- A YOLOv7 CRDDC entry scored 81.7% F1 on US (Google Street View) data but 74.1% on all challenge data. This shows a large cross-country generalisation gap. — [arXiv 2211.00091](https://arxiv.org/abs/2211.00091v1)
- RDD2022 has 47,420 images (cited as the comparison point in RoadBench). — [RoadBench, arXiv 2507.17353](https://arxiv.org/html/2507.17353v1)
- ORDDC'2024 (Optimized Road Damage Detection Challenge, IEEE BigData 2024) scored both accuracy and speed. The 4th-place entry, an ensemble of a custom YOLOv7 with Coordinate Attention plus Tiny YOLOv7, reached 0.7027 F1 at about 0.0547 s per image. — [Pham et al., arXiv 2410.08409](https://arxiv.org/abs/2410.08409v1)
- The USC InfoLab ORDDC2024 repo reports 0.7017 F1 at 0.0432 s per image in Phase 2, and 0.7664 F1 on 6 countries in Phase 1. — [USC-InfoLab/orddc2024 (mirror)](https://gh.r-mj.com/USC-InfoLab/orddc2024)
- StripRFNet (Oct 2025) cites the ORDDC'2024 champion at 37.2 ms with F1 79.27, but that number is on full RDD2022 and may not match the official leaderboard. — [StripRFNet, arXiv 2510.16115](https://arxiv.org/pdf/2510.16115)
- YOLO11 variants on RDD2022 (2025):
  - A wavelet-convolution YOLOv11 reports 86.5% average mAP@50, which is +2% over baseline with about 17% fewer parameters. — [CMC 2025](https://www.techscience.com/cmc/v85n1/63529)
  - YOLOv11-ATL (tiny-object layer) reports +3.2 mAP@0.5 and +3.1 mAP@0.5:0.95. — [PLOS ONE / PMC12469154](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12469154/)
  - An improved YOLO11 with RoadRep-C3, EMA attention and a hypergraph neck reports +2% mAP@0.5 with a smaller model. — [Promet](https://traffic2.fpz.hr/index.php/PROMTT/article/view/1128)
  - RPP-YOLOv11 (RGB-thermal fusion) reports 69.04% mAP@0.5 and 42.70% mAP@0.5:0.95. — [PLOS ONE (EconPapers)](https://econpapers.repec.org/RePEc:plo:pone00:0355111)
- These papers use different splits and training setups, so their absolute mAP values cannot be compared with each other (noted in the search summary for the sources above).
- ViSnow (ETS Montreal): about 294,000 images covering day/night, snow, rain and clear conditions. Images are labelled with 4 snow-cover classes (clear, light-covered, medium-to-heavy-covered, plowed). There are no damage labels. DOI 10.21227/9dyz-x716. — [IEEE DataPort ViSnow](https://ieee-dataport.org/node/12819); [ETS record](https://pure.etsmtl.ca/en/datasets/visnow-snow-covered-urban-roads-dataset-for-computer-vision-appli/)
- A companion auto-annotation system covers over 41,000 images across weather and time-of-day conditions. EfficientNet trained on separate day and night sets reaches 97% precision and recall. — [Sboui et al. 2024, ETS](https://espace2.etsmtl.ca/28679/1/Sboui-L-2024-28679.pdf)
- A McGill thesis (Ce Zhang) covers cracks, potholes and winter surface conditions using visible and thermal video collected on Montreal pavements. It is a thesis, not a confirmed public dataset. — [McGill eScholarship](https://escholarship.mcgill.ca/downloads/qf85nh065)
- DRDD (from the RDD4D paper): 1,500 GoPro images with 5 damage types, captured in varied weather and at varied times of day. It is not Canadian. — [RDD4D, arXiv 2501.02822](https://arxiv.org/pdf/2501.02822)
- RoadBench: 100,000 image-text pairs at 3840x2160 covering 10 damage types (longitudinal, transverse, alligator, pothole, patch, edge crack, centerline crack, discoloration, mixed, unknown). It is listed as "Public", but the page gives no download link or licence. — [RoadBench, arXiv 2507.17353](https://arxiv.org/html/2507.17353v1)

### Inferences
- For a Halifax pilot, a single YOLO11-s/m fine-tuned on RDD2022 plus locally labelled Halifax footage is probably close to the achievable frontier. Ensembles add only a few F1 points at 2-3x the compute. The 81.7% vs 74.1% gap shows domain shift matters more than architecture.
- ViSnow could be used for a winter-condition gating classifier (for example, suppressing damage detections when the road is snow-covered, or adding a snow-clearing feature). It cannot train the damage detector itself.
- Thermal fusion (RPP-YOLOv11) is a possible night or winter robustness path, but it needs extra hardware.

### Gaps
- No verified RT-DETR / RT-DETRv2 / D-FINE result on RDD2022 was found, and no official ORDDC'2024 leaderboard or organiser summary was found.
- No CRDDC 2025/2026 successor challenge was confirmed.
- No verified segmentation benchmark (instance masks for area) on an RDD-style dataset was found in this budget.
- Ultralytics "YOLO26" appeared in a page title but was not verified, so it has no numbers here.
- No public Canadian winter road-damage dataset with damage labels was found.

## Severity and measurement: pothole size/depth from monocular video, smartphone IRI, PCI/PASER mapping

### Takeaway
Monocular depth foundation models (Depth Anything V2/V3) can now give pothole area and relative depth from dashcam video. Metric depth or volume from a single camera is still unreliable. Smartphone accelerometer IRI reaches about R²≈0.79 against profiler ground truth, but results depend heavily on vehicle, mounting and speed. Image-to-PCI and image-to-PASER models exist, which supports adding a standardised condition score.

### Cited Findings
- A video-based pothole area estimation method (May 2025) pairs a detector with per-frame DepthAnything V2 depth maps and Kalman smoothing. A distilled DepthAnything V2 shrinks from 4,439.5 MB to 86.2 MB "while maintaining high accuracy", and depth estimation is the runtime bottleneck. The authors note prior geometric methods assume flat roads and are sensitive to camera angle. — [arXiv 2505.21049](https://arxiv.org/pdf/2505.21049)
- A 2026 preprint testing Depth Anything V3 for pothole measurement finds it does not recover metric depth, only relative depth. — [Kumoh NIT abstract (GLBIO 2026)](https://d2j16w31g89z0j.cloudfront.net/site/2026w/abs/0680-GLBIO.pdf)
- A BMVC 2025 workshop paper fuses RGB detectors with a DINOv2-based depth detector using monocular images only, with no stereo or LiDAR. — [BMVC 2025 DIFA workshop](https://bmva-archive.org.uk/bmvc/2025/assets/workshops/DIFA/Paper_2/paper.pdf)
- Smartphone IRI: a deep-learning model on smartphone accelerometer, gyroscope and speed data reached R²=0.79 against MoDOT ARAN IRI. — [Mobile Sensing review, arXiv 2106.10733](https://arxiv.org/pdf/2106.10733)
- Smartphone roughness accuracy depends on phone type and position and on vehicle type, speed, mass, suspension and tyre pressure. Regression models reach roughly visual-inspection-level accuracy. — [ASCE J. Infrastructure Systems](https://ascelibrary.com/doi/10.1061/%28ASCE%29IS.1943-555X.0000558)
- A 2023 IJPE paper proposed standard repeatability and accuracy metrics for smartphone IRI systems because earlier studies used inconsistent definitions. — [IJPE 2023](https://informahealthcare.com/doi/abs/10.1080/10298436.2023.2183402)
- University of New Brunswick (TAC) proof of concept: the smartphone vs high-speed profiler IRI correlation was "strong enough to warrant a larger study" on a 2 km section. This is a Maritime-Canada precedent. — [TAC Hanson paper](https://www.tac-atc.ca/wp-content/uploads/hanson.pdf)
- An edge-computing road-condition system reached 88.6% accuracy on 3 classes (rough/average/smooth). — [arXiv 2310.05321](https://arxiv.org/pdf/2310.05321)
- Image-to-PCI:
  - An improved ResNet50 with spatial and channel attention predicts PCI directly from pavement images. — [arXiv 2504.18490](https://arxiv.org/html/2504.18490v1)
  - PaveCap (USDOT Region 8) combines YOLOv8 and SAM for single-shot PCI with natural-language explanations. — [ROSAP dot 94246](https://rosap.ntl.bts.gov/view/dot/94246/dot_94246_DS1.pdf)
  - Toronto Metropolitan University estimated PCI from Google Street View imagery. — [ISPRS 2024](https://isprs-archives.copernicus.org/articles/XLVIII-M-4-2024/47/2024/isprs-archives-XLVIII-M-4-2024-47-2024.pdf)
- PASER from vehicle data: Detroit and Tactile Mobility derived PASER ratings from sensors on about 20 city-owned Ford trucks, with monthly pothole maps. — [Route Fifty](https://www.route-fifty.com/digital-government/2022/01/detroit-tests-cloud-enabled-pavement-monitoring/360860/?oref=rf-next-story)
- Zero-shot LLM/VLM scoring of pavement severity against PSCI (Pavement Surface Condition Index) has been tested with prompt engineering (UCC, 2025). — [arXiv 2504.06785](https://arxiv.org/abs/2504.06785v1)

### Inferences
- A practical severity upgrade has three parts:
  - Segmentation masks for area.
  - Relative depth from a distilled Depth Anything model, scaled using known camera height and lane width, or multi-frame SfM.
  - Phone accelerometer "jolt" magnitude as a corroborating severity signal.
- Report severity as a band rather than claiming metric depth.
- Reporting a PASER (1-10) band per segment would match what Canadian municipalities already use and give Halifax a familiar output.

### Gaps
- No verified paper giving pothole volume error (cm³ or % error) from monocular dashcam video was found.
- No quantitative SfM/COLMAP-based pothole depth accuracy was found in this budget.
- Halifax's own pavement-rating scheme (PCI vs PASER vs in-house) was not checked.

## Vision-language models and agents: verification accuracy and cost, small/local VLMs, MCP patterns, evaluating agent decisions

### Takeaway
General-purpose VLMs are mediocre zero-shot road-damage judges. GPT-4V scores about 74.5% zero-shot accuracy on RoadBench, while the fine-tuned RoadCLIP scores 78.6%. Zero-shot outputs can be vague or wrong. This supports RoadSense's design of using the VLM as a second-opinion verifier, not as the primary detector. Cheap models (Gemini 2.5 Flash-Lite at $0.10/M input tokens, Qwen2.5-VL-7B at about $0.20/M on OpenRouter) make per-detection verification cost fractions of a cent.

### Cited Findings
- RoadBench (Table 2) zero-shot accuracy: RoadCLIP 78.6%, GPT-4V 74.5%, DeepSeek-VL 72.9%, CLIP 63.8%.
- RoadBench Recall@1: RoadCLIP 58.4%, GPT-4V 52.6%, CLIP 40.3%.
- RoadBench semantic localisation accuracy: RoadCLIP 61.9%, GPT-4V 55.4%, best vision-only model (TD-YOLOv10) 49.0%.
- RoadBench cross-dataset zero-shot accuracy on TD-RD: RoadCLIP 74.3%, GPT-4V 71.2%. The text names both GPT-4V and GPT-4o, while the tables say GPT-4V. — [RoadBench, arXiv 2507.17353](https://arxiv.org/html/2507.17353v1)
- RoadBench authors state general foundation models (GPT-4o, DeepSeek-VL) "yield poor performance" on road damage understanding. They used GPT-4o to caption the 100k-image dataset. — [RoadBench](https://arxiv.org/html/2507.17353v1)
- V-RoAst: zero-shot GPT-4o-mini and Gemini-1.5-Flash can code iRAP road attributes, but score lower than VGGNet and ResNet baselines. — [V-RoAst, arXiv 2408.10872](https://arxiv.org/html/2408.10872v3)
- Prajapati et al. compared CLIP, BLIP, OWL-ViT, LLaVA-Next and GPT-4o on transportation tasks, including binary crack detection. The numbers were not retrieved. — [arXiv 2504.06785 review](https://www.themoonlight.io/review/evaluation-and-comparison-of-visual-language-models-for-transportation-engineering-problems)
- An April 2026 arXiv paper reports that zero-shot VLM pavement outputs can be vague or wrong (for example, describing cracked pavement as having "uniform texture"), while instruction-tuned models are more accurate. — [arXiv 2604.08212](https://arxiv.org/pdf/2604.08212)
- A study evaluated 4 GPT-based VLMs against 3 pavement experts on 364 Google Street View images. — [TRID 2716697](https://trid.trb.org/View/2716697)
- Pricing (secondary aggregators; check live pages):
  - Qwen2.5-VL-7B on OpenRouter is about $0.20/M input and $0.20/M output tokens. — [OpenRouter Qwen VL listing](https://openrouter.ai/qwen/qwen-2-vl-7b-instruct/api); [llmbase](https://llmbase.ai/models/qwen/qwen-2.5-vl-7b-instruct)
  - Gemini 2.5 Flash-Lite is $0.10/M input (text, image and video), $0.40/M output, and $0.05/M batch input. — [cloudprice](https://cloudprice.net/models/gemini-2-5-flash-lite); [SD Times](https://sdtimes.com/ai/gemini-2-5-pro-and-flash-are-generally-available-and-gemini-2-5-flash-lite-preview-is-announced/)

### Inferences
- At about 1,000-1,500 image tokens per crop plus a short JSON answer, a verification call on Flash-Lite or Qwen2.5-VL-7B costs roughly $0.0001-0.0003. 10,000 detections a month would be a few dollars, so VLM cost is not the constraint. Accuracy and latency are. (This is a back-of-envelope estimate; image token counts vary by model.)
- Cost-cutting options:
  - Cascade: a cheap VLM first, escalating to a frontier model only on disagreement or low confidence.
  - Batch APIs, which halve input cost.
  - A local Qwen2.5-VL-7B on a workstation or a Jetson AGX-class device.
- Fine-tuning a CLIP-style or small VLM on RDD-style plus Halifax data (the RoadCLIP approach) beats GPT-4V zero-shot on RoadBench and would remove per-call API cost.
- Agent evaluation: build a labelled "golden set" of detections with ground-truth verify, dedupe and severity outcomes, plus the human-approval decisions, and score each agent step. Human approve and reject actions in RoadSense are a free source of labels.

### Gaps
- No verified published benchmark of MCP-specific agent patterns or agent-decision evaluation frameworks for this domain (searches not run within budget).
- No verified per-image latency figures for the VLMs.
- No measured accuracy of small local VLMs (Qwen2.5-VL-3B/7B, Gemma 3, Moondream) on road damage was found.

## Data capture and scale: fleet dashcams, smartphone apps, OEM connected-vehicle data, edge hardware, bandwidth/cost

### Takeaway
Municipal fleet cameras on sweepers, garbage trucks and city trucks are the proven scale path. San José reported a 97% pothole true-positive rate in a 2023-24 pilot. OEM data (Mercedes-Benz Surface Events in Boston, Ford trucks with Tactile in Detroit) gives sensor-only coverage without imagery. For edge compute, the $249 Jetson Orin Nano Super and a Raspberry Pi 5 with Hailo-8 (about 2.5 W) both run YOLOv8s-class models at real-time rates.

### Cited Findings
- San José Road Safety Conditions Pilot (Dec 2023 to Jul 2024) used AI on footage from city vehicles, mainly in District 10, and tested 4 vendors. It reports a 97% true-positive rate for potholes, while 72-hour parking detection was unreliable. No operational changes have been made yet. — [Cities Today](https://cities-today.com/?p=72693); [StateScoop](https://statescoop.com/?p=68671)
- Memphis Public Works runs cameras on 4 city trucks (one forward-facing, one facing the sidewalk side). They detect potholes, clogged storm drains, high grass and illegal dumping. — [AP via Boston.com](https://www.boston.com/news/local-news/2025/11/16/cities-and-states-are-turning-to-ai-to-improve-road-safety)
- Commercial fleet products:
  - Rubicon puts AI cameras on waste and recycling trucks to detect potholes and contamination. — [AP via The Star](https://www.thestar.com.my/tech/tech-news/2025/11/17/us-cities-and-states-are-turning-to-ai-to-improve-road-safety)
  - Samsara "Ground Intelligence" turns commercial trucks into pothole detectors.
  - Blyncsy combines dashcam feeds with mapping. — same AP source
  - Routeware markets connected trucks for pothole detection. — [Routeware](https://routeware.com/?p=28105)
- Mercedes-Benz "Surface Events" sells road-surface damage events from its connected fleet. It is used by Boston and by the Netherlands ministry. — [Mercedes-Benz Data](https://data.mercedes-benz.com/products/surface-events); [IoT World Today](https://iotworldtoday.com/transportation-logistics/connected-mercedes-vehicles-to-improve-boston-s-roads)
- GM has filed a patent for vehicle-sensor road-damage prediction. This is not a deployed product. GM stopped selling driving data to risk-profiling firms after consent lawsuits. — [NewsBytes](https://www.newsbytesapp.com/news/auto/gms-new-system-predicts-road-damage-using-car-sensors/tldr); [The Star](https://thestar.com.my/tech/tech-news/2024/12/31/how-your-car-might-be-making-roads-safer)
- Edge hardware (secondary review sites; figures conflict):
  - Jetson Orin Nano Super dev kit costs $249 and is rated 67 TOPS (sparse INT8; about 33-34 dense). — [CNX Software](https://cnx-software.com/2024/12/18/249-nvidia-jetson-orin-nano-super-developer-kit-targets-generative-ai-applications-at-the-edge/); [SpecPicks](https://specpicks.com/reviews/pi-5-hailo-8-vs-jetson-orin-nano-super-vision-2026)
  - Hailo-8 is 26 TOPS at about 2.5 W, versus 7-25 W for the Orin Nano Super. — [Geniatech](https://www.geniatech.com/hailo-10-vs-nvidia-jetson-edge-ai/)
  - A Pi 5 with Hailo-8 costs about $150-190 in total. — [SpecPicks](https://specpicks.com/reviews/jetson-orin-nano-super-vs-hailo-8-ai-hat-2026)
  - One comparison: YOLOv8n about 190 FPS (Hailo) vs 170 FPS (Jetson); YOLOv8s about 95 vs 92; YOLOv8m about 38 vs 52 (Jetson ahead). — [SpecPicks](https://specpicks.com/reviews/pi-5-hailo-8-vs-jetson-orin-nano-super-vision-2026)
  - Another source relays NVIDIA Jetson AI Lab figures of 32-40 FPS for YOLOv8n with TensorRT FP16. The methodology clearly differs. — [SpecPicks](https://specpicks.com/reviews/jetson-orin-nano-super-vs-raspberry-pi-5-edge-ai-benchmarks-2026)
  - The Jetson can also run CUDA and small LLMs/VLMs. Hailo-8 cannot. — same source
- Ultralytics has published a guide to running YOLO11 on Jetson Orin Nano Super. — [Ultralytics blog](https://www.ultralytics.com/ja/blog/ultralytics-yolo11-on-nvidia-jetson-orin-nano-super-fast-and-efficient)

### Inferences
- The strongest Halifax extension is to mount the existing on-device pipeline on Halifax Transit buses or solid-waste contractor trucks, which repeat routes weekly. The San José and Memphis precedents are directly relevant for procurement conversations.
- On-device detection and blurring means only event crops plus metadata are uploaded, not continuous video. At tens of KB per event, bandwidth is negligible compared with streaming. (Inference, not measured.)
- Choose Hailo for low-power, detector-only units. Choose Jetson if an on-vehicle VLM or depth model is wanted.
- OEM data such as Mercedes Surface Events could add a roughness/pothole prior with no RoadSense hardware. Canadian availability is unverified.

### Gaps
- Phone NPU benchmarks (Snapdragon, Apple Neural Engine) for YOLO11 were not retrieved.
- Vialytics (smartphone-based, used by European municipalities) and RoadAI (Vaisala) were not found in search, so no numbers are available.
- No verified per-vehicle cost of fleet camera programmes was found.
- Cellular data cost in Canada was not researched.

## Change detection, forecasting, digital twins, GIS, multi-hazard extensions

### Takeaway
Most published work estimates current PCI from images. True forecasting from repeated imagery is still emerging: a 2026 graph-network preprint (ST-ResGAT) forecasts PCI trajectories using road-network topology. Multi-hazard extensions are commercially proven (Memphis detects storm drains, grass and dumping). Sidewalk accessibility has a mature open dataset and models (Project Sidewalk). No source was found on AI verification of snow clearing.

### Cited Findings
- ST-ResGAT (arXiv 2603.14107, 2026) forecasts future PCI trajectories using network topology and neighbour influence. It maps forecasts to ASTM D6433 condition categories for maintenance prioritisation. — [arXiv 2603.14107](https://arxiv.org/pdf/2603.14107)
- A 2025 review covers ML and DL for PCI and service-life prediction. — [EJMCA 2025](https://ejmca.enu.kz/assets/files/13-4-4.pdf)
- Memphis city-truck cameras detect potholes, clogged storm drains, high grass and illegal dumping. — [AP via Boston.com](https://www.boston.com/news/local-news/2025/11/16/cities-and-states-are-turning-to-ai-to-improve-road-safety)
- Project Sidewalk:
  - A 2018 DC pilot drew about 1,400 users who audited about 2,934 km and produced 250,000 labels.
  - By ASSETS 2024 it was deployed in 21 cities across 8 countries.
  - Deep-learning benchmarks cover 33 sidewalk-condition classes on 640x640 crops, with an open dataset released. — [ASSETS 2024 paper](https://makeabilitylab.cs.washington.edu/media/publications/Liu_TowardsFineGrainedSidewalkAccessibilityAssessmentWithDeepLearningInitialBenchmarksAndAnOpenDataset_ASSETS2024.pdf); [arXiv 2206.13677](https://arxiv.org/pdf/2206.13677)
- ACAMAI applied YOLOv8 to Street View panoramas to find accessibility barriers in Porto, combining Project Sidewalk data with local data. — [UFP thesis](https://bdigital.ufp.pt/bitstreams/00e39a49-0f57-4443-a00c-361d278d785b/download)
- ViSnow's "plowed surface" class (see Detection) is a ready-made label for a snow-clearing verification classifier. — [IEEE DataPort ViSnow](https://ieee-dataport.org/node/12819)

### Inferences
- RoadSense's dedupe-by-location already creates a time series per defect. Storing each sighting's mask area and severity gives deterioration curves per defect (growth rate) at almost no extra cost. This is a differentiator compared with one-off surveys, and it feeds ST-ResGAT-style network forecasting later.
- Snow-clearing verification is a plausible Halifax-specific product. A ViSnow-trained classifier on bus or plow footage, joined to plow GPS, could check service-standard compliance. No vendor or paper evidence was found, so the novelty and risk are both high.
- Exporting to GIS through standard formats (GeoJSON/ArcGIS feature services) and linking to the municipal asset inventory is the usual integration path (general knowledge, not sourced here).

### Gaps
- No sources were retrieved on lane-marking retroreflectivity or wear detection, signage inventory, or debris detection benchmarks.
- No sources were retrieved on digital-twin platforms (for example Esri or Bentley) for pavement.
- No published snow-plow or clearing verification by camera was found.

## Privacy tech: anonymisation (EgoBlur), on-device processing, federated learning

### Takeaway
EgoBlur (Meta, Apache 2.0) is the strongest open face and plate anonymiser, with AP 0.99 and recall 0.998 on faces. It is heavy, though: about 104M parameters, about 0.5 s per 2 MP frame on GPU and about 8 s on CPU. It suits server-side or audit re-blurring rather than real-time edge use. Federated learning for road damage is research-stage, reaching about 0.74 mAP@50 for potholes, with non-IID data and communication cost as the main obstacles.

### Cited Findings
- EgoBlur uses Faster R-CNN with a ResNeXt backbone for both face and plate models. It was trained on 23M images and 790M boxes. Each model is about 400 MB and about 104M parameters, with inference about 0.5 s on GPU and about 8 s on CPU per 2 MP image. It is licensed Apache 2.0 for research and commercial use. — [Project Aria EgoBlur docs](https://facebookresearch.github.io/projectaria_tools/docs/open_models/egoblur); [projectaria.com](https://projectaria.com/tools/egoblur)
- EgoBlur face detection reaches AP 0.99 and recall 0.998, tying RetinaFace and beating MediaPipe (0.979/0.99). It reports more than 90% recall on hard benchmarks, is on par with other models on non-egocentric data, and is better on egocentric data. All of these figures are Meta's own. — [EgoBlur paper, arXiv 2308.13093](https://arxiv.org/pdf/2308.13093v2.pdf)
- An independent but informal comparison judged EgoBlur better than NVIDIA LPDNet on licence plates, by subjective assessment. — [Starschema blog](https://medium.com/starschema-blog/nvidia-lpdnet-vs-meta-egoblur-blurring-license-plates-with-deep-learning-d7cc2d770685)
- FedRD (2021) is edge-cloud federated road-damage detection with individualised differential privacy and pixelisation. — [U. Brighton](https://research.brighton.ac.uk/en/publications/fedrd-privacy-preserving-adaptive-federated-learning-framework-fo/)
- RoadFed (2025) is multimodal (image plus text) federated hazard detection with a low-error local differential privacy method. — [arXiv 2502.09978](https://arxiv.org/pdf/2502.09978)
- Federated pothole detection (2025): FedGH reaches mAP@50 0.74 and mAP@50-95 0.506, outperforming FedAvg under heterogeneity. — [TRID 2729384](https://trid.trb.org/View/2729384)
- Consistency-guided model-contrastive FL for multi-country road damage detection has been published (Automation in Construction, per TRID). — [TRID 2733106](https://trid.trb.org/View/2733106)
- GM's exit from data-selling after consent lawsuits shows the regulatory and reputational risk of vehicle data. — [The Star](https://thestar.com.my/tech/tech-news/2024/12/31/how-your-car-might-be-making-roads-safer)

### Inferences
- Recommended pattern:
  - A lightweight on-device blur (a small YOLO face and plate model) before any upload.
  - Server-side EgoBlur as a second pass on the few crops that are stored or sent in Open311 reports.
  - Log both passes as evidence for PIPEDA / Nova Scotia FOIPOP privacy reviews.
- Federated learning is not needed for a single-city pilot. It becomes relevant if ride-share or citizen phones contribute and raw frames should never leave devices. Event-crop upload with on-device blur gets most of the privacy benefit at much lower complexity.

### Gaps
- No independent benchmark of EgoBlur on dashcam (non-egocentric, low-light, winter) footage was found.
- No verified latency for small edge face and plate blurring models was found.
- Canadian privacy-law specifics (PIPEDA, NS FOIPOP, OPC guidance on dashcams) were not researched here.
