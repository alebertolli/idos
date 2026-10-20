# Changelog

## [0.1.5](https://github.com/alebertolli/idos/compare/v0.1.4...v0.1.5) (2026-10-20)


### Features

* **strategy:** route enabled monthly profiles ([dd1ae3c](https://github.com/alebertolli/idos/commit/dd1ae3c95d2c2ccef50067eab45761ed19635513))


### Bug Fixes

* **data:** reconcile financial observations by period ([#128](https://github.com/alebertolli/idos/issues/128)) ([b5c4871](https://github.com/alebertolli/idos/commit/b5c4871c0e17add9608d0267b6239b303bd5f68a))
* preserve bounded ticker scope through DDD ([71274d4](https://github.com/alebertolli/idos/commit/71274d4e13f145dfb870e647c8a0a89de2dea002))
* route ETF refresh directly to Yahoo ([#142](https://github.com/alebertolli/idos/issues/142)) ([026ced6](https://github.com/alebertolli/idos/commit/026ced6b7956b0b1b078c15b8a3e83f3f94435d1))
* validate research scenarios against supplied evidence ([26d2cd6](https://github.com/alebertolli/idos/commit/26d2cd6d84e4a7f2011febb34ee5015ee0627588))


### Documentation

* record production multi-strategy E2E ([#141](https://github.com/alebertolli/idos/issues/141)) ([64c1b11](https://github.com/alebertolli/idos/commit/64c1b1195b086f8194bb0d54fc1f5b0d4bbd49cf))

## [0.1.4](https://github.com/alebertolli/idos/compare/v0.1.3...v0.1.4) (2026-10-20)


### Features

* **workflows:** allow bounded production E2E opt-in ([89aa63a](https://github.com/alebertolli/idos/commit/89aa63a21c3daffbe02af9c55e731855f49dbf32))


### Documentation

* clarify clean history candidate commit chain ([03c5066](https://github.com/alebertolli/idos/commit/03c506699ad8928bf656626fd88ce31f4bc81247))
* **e2e:** record bounded production run results ([ff8efb6](https://github.com/alebertolli/idos/commit/ff8efb6a087ec4f0ce5e5d283d75d9026a83dabf))
* keep baseline history description stable ([db8debf](https://github.com/alebertolli/idos/commit/db8debf2fbe0da931962f30d4b3debee71a0cb74))
* record clean main reset and validation ([84b058d](https://github.com/alebertolli/idos/commit/84b058d711487283f9d5c0a72e73bbd5189c0e42))
* record clean main reset preparation and safeguards ([ce91011](https://github.com/alebertolli/idos/commit/ce91011e635110391cda6772916105ab1e0ecffe))

## [0.1.3](https://github.com/alebertolli/idos/compare/v0.1.2...v0.1.3) (2026-10-20)


### Bug Fixes

* preserve StockAnalysis financial cutoff provenance ([d7e671d](https://github.com/alebertolli/idos/commit/d7e671dd47cece9173b13ffa1e4bc9d2878ed628))
* stash transient DDD outputs before rebase ([f6b343e](https://github.com/alebertolli/idos/commit/f6b343e4dd9d61a79295808094546649668a70cc))

## [0.1.2](https://github.com/alebertolli/idos/compare/v0.1.1...v0.1.2) (2026-10-20)


### Bug Fixes

* distinguish levered and unlevered FCF ([a642af0](https://github.com/alebertolli/idos/commit/a642af01337e2b9c03b30c37c3d78b816c0bd343))
* keep portfolio runtime disabled until private source validation ([2f44c88](https://github.com/alebertolli/idos/commit/2f44c88cedc2dba4c24171a7c8c0e2feaea490b2))
* separate levered and unlevered FCF; document E2E ([68436ee](https://github.com/alebertolli/idos/commit/68436eedfe18ec1a63609d7dd620656fca525022))
* separate revenue growth forecasts from actuals ([#109](https://github.com/alebertolli/idos/issues/109)) ([4974ca7](https://github.com/alebertolli/idos/commit/4974ca79def9332d9a0706cde5ab87d17754ce47))


### Documentation

* record bounded end-to-end validation ([54561ee](https://github.com/alebertolli/idos/commit/54561eec389c2411cca6dc6fae2613fa1d5b5966))
* record disabled portfolio gate E2E ([835a72e](https://github.com/alebertolli/idos/commit/835a72e8766a6bc513c06e5f64d3d2b73542e256))
* record StockAnalysis E2E validation ([#110](https://github.com/alebertolli/idos/issues/110)) ([4475918](https://github.com/alebertolli/idos/commit/44759189b53ae46418e0a2d696a2d7fce62a2651))

## [0.1.1](https://github.com/alebertolli/idos/compare/v0.1.0...v0.1.1) (2026-10-01)


### Features

* add --preview step to ddd-pipeline to list candidates before processing ([0a2edbc](https://github.com/alebertolli/idos/commit/0a2edbc38df691432ba3c9f75693684d2144d8cf))
* add multi-strategy IDOS pipeline ([ed213c9](https://github.com/alebertolli/idos/commit/ed213c937b4e5dbac8d8ef15847753f57538fdfb))
* new state model SCREENED/WATCHLIST/UNDER_RESEARCH ([7cdb6e4](https://github.com/alebertolli/idos/commit/7cdb6e454814cd9f71f3c420da38a1964fa4855c))
* stale alerts scoped to UNDER_RESEARCH/SCREENED; thesis_not_assessed alerts for portfolio; SDD-7 v2.3 ([9355cba](https://github.com/alebertolli/idos/commit/9355cbaf2877d2ec1173f1decbef41a9e9bd6b3d))
* UNDER_RESEARCH only score&gt;=60 not in buy-list/portfolio; DDD pipeline runs only on stale (&gt;30d) or missing thesis ([7054508](https://github.com/alebertolli/idos/commit/7054508c056915108b4ed5356bbe4236c220ba8b))


### Bug Fixes

* allow UNDER_RESEARCH-&gt;UNDER_RESEARCH re-research + YAML restore ([a770539](https://github.com/alebertolli/idos/commit/a770539180c1e777be4b8ed751d838135d9354f7))
* **assessment_pipeline:** preserve UNDER_RESEARCH when rules fail; verify all 35 UNDER_RESEARCH rules correct; populate AGREGADO with file mtime AR timezone ([a6b48cd](https://github.com/alebertolli/idos/commit/a6b48cd426c482180da024b0e62247fde73dd4ad))
* **assessment_pipeline:** set last_research_at on re-process to clear stale alerts ([9ee6986](https://github.com/alebertolli/idos/commit/9ee69866f177fda7f0c98b8bcc9f7fe6efa71491))
* configure release please manifest ([709b71c](https://github.com/alebertolli/idos/commit/709b71c9db962989879e2cf35bd320052fa9d1f8))
* ddd pipeline auto-detects stale UNDER_RESEARCH &gt;30d and forces re-research ([b471ee9](https://github.com/alebertolli/idos/commit/b471ee9359210c52d3f892e4a93977b40dbb4d8a))
* ddd_research.py now executes ResearchWorker for stale opps (not just selection) ([d1361e3](https://github.com/alebertolli/idos/commit/d1361e36ade450070be7f2e8c2127c36955bbca4))
* decision rules use correct domain keys + force_reprocess updates last_research_at ([a2bec3b](https://github.com/alebertolli/idos/commit/a2bec3b6fc1ed754ff2aedb24178596b4d8226b3))
* Discovery view shows 267 operable pool; Research view includes both UNDER_RESEARCH and legacy UNDER_DEEP_DD ([aba89d1](https://github.com/alebertolli/idos/commit/aba89d14693bebde68ce9ecba0d18066d1dc5926))
* expose IDE metrics and route momentum research ([5bf2064](https://github.com/alebertolli/idos/commit/5bf2064bc5ba5b95c02492321f62b120074825d7))
* handle None config in ResearchWorker.__init__; migrate remaining UNDER_DEEP_DD to UNDER_RESEARCH ([dc98047](https://github.com/alebertolli/idos/commit/dc980472f2e3b51c91f27ca72535688604b23dca))
* monthly evaluation skip tickers not in current universe ([f05a948](https://github.com/alebertolli/idos/commit/f05a948ca0c2bb372ed650f072494a95fd76406f))
* preserve UNDER_RESEARCH when rules fail; populate AGREGADO column from file mtime ([268b059](https://github.com/alebertolli/idos/commit/268b059becd427a8c735b4d538c0062ee471a1ca))
* read Scout scores from cache JSON files; trim discovery_pool to universe_stats.operable_count; merge watchlist into Research view ([deac2ea](https://github.com/alebertolli/idos/commit/deac2ea4b91ee92f999913fea5ee24a5cf3dd396))
* remove shell quoting from monthly pipeline ([1dd5ece](https://github.com/alebertolli/idos/commit/1dd5ece62893ad2cc58d5de62240cd34b7859633))
* restore correct opps to UNDER_RESEARCH (score&gt;=60 with DDD report), demote &lt;60 ([cf79d70](https://github.com/alebertolli/idos/commit/cf79d7086a9462efa26b99782501d5148f5f2653))
* save decision under real ticker, not 'OPP' + deprecate DecisionBoardWorker ([2b02d22](https://github.com/alebertolli/idos/commit/2b02d228748b7afc3127f1d5aad452ff2504ca50))
* **site:** added_at uses AR timezone (-03:00) ([164f03e](https://github.com/alebertolli/idos/commit/164f03efd46eddc1caacdb1e7d190e2cbd514b27))
* use last_research_at (set by ResearchWorker) as primary source for staleness detection in UI ([fc42281](https://github.com/alebertolli/idos/commit/fc42281c8ec76b1422eab2736d942a211c8bb3ef))

## Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!-- releaseme:start placeholder -->
<!-- releaseme:end placeholder -->
