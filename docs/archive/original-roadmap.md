# Original Phase-Wise Project Roadmap (Archived)

> [!NOTE]
> This document archives the initial 5-phase project conceptualization and theoretical work allocation plan for the 10-member team prior to the focused 3-sprint production architecture migration (DRCH).

---

## Granular Phase-Wise Work Allocation for All 10 Members

### Phase 1: Foundation, Schemas, Prototypes & Environment Setup (Weeks 1 - 2)
*Goal: Establish system contracts, development environments, baseline microservices, and ingestion schemas.*

- **Member 1 (Architect)**: 
  - Design system architecture, service dependency graph, and OpenAPI/REST specification.
  - Setup core repository, database migration templates (PostgreSQL/PostGIS), and shared data models (`Incident`, `Alert`, `TriageResult`, `UserRole`).
- **Member 2 (Gov/Telecom)**: 
  - Document C-DAC ERSS 112 API/VPN simulation specifications and mock data generator.
  - Implement parser prototype for NDMA SACHET XML Common Alerting Protocol (CAP) schema.
- **Member 3 (Indic NLP & GenAI)**: 
  - Setup social media ingestion connectors (Twitter/X API v2 mock, Telegram distress bot, WhatsApp Business webhook sandbox).
  - Benchmark Indic-BERT / multilingual LLM models on Hindi, Marathi, Bengali, Tamil, Telugu, and Hinglish sample posts.
- **Member 4 (Drone CV)**: 
  - Collect and curate drone footage dataset with simulated weather degradation (fog, downpour, heavy smoke).
  - Research sensor degradation profiles (MPU6050 IMU drift and VL53L5CX ToF sensor noise filters under water droplets).
- **Member 5 (Geospatial)**: 
  - Define PostGIS geospatial indexes, H3 hexagonal hierarchical spatial indexes (resolutions 7-9).
  - Formulate NDMA Incident Response System (IRS) severity matrix rules (Scale 1–5 based on life risk, critical infrastructure impact, and environmental hazard).
- **Member 6 (GIS Map UI)**: 
  - Initialize React / Next.js GIS frontend application with TailwindCSS/Vanilla CSS design system.
  - Integrate Leaflet / Mapbox GL JS basemap tiles with multi-layer toggle support.
- **Member 7 (Role Dashboards)**: 
  - Wireframe and implement interactive UI shells for Incident Commander, Operations Section Chief, and Logistics Section Chief.
  - Implement reusable UI design tokens, breadcrumb navigation, and responsive layouts.
- **Member 8 (Real-Time & Sync)**: 
  - Benchmark message brokers: Apache Kafka vs RabbitMQ vs Redis Streams for disaster event telemetry.
  - Implement WebSocket gateway prototype with client heartbeat and reconnection recovery.
- **Member 9 (Compliance & Summarizer)**: 
  - Audit regulatory compliance requirements: Digital Personal Data Protection (DPDP) Act 2023, NDMA Guidelines, and C-DAC ERSS 112 standards.
  - Implement regex and Named Entity Recognition (NER) pipeline for redacting Citizen PII.
- **Member 10 (DevOps & QA)**: 
  - Configure root Docker Compose environment with containerized PostgreSQL 16 + PostGIS 3.4.
  - Author automated smoke test scripts (`scripts/smoke.sh`) and configure GitHub Actions CI workflow.

---

### Phase 2: Core Microservices & Pipeline Engineering (Weeks 3 - 4)
*Goal: Implement data ingestion pipelines, AI inference workers, spatial queries, and authentication.*

- **Member 1 (Architect)**: 
  - Implement OAuth 2.0 / JWT stateless authentication, Argon2id password hashing, and role-based access control (RBAC).
- **Member 2 (Gov/Telecom)**: 
  - Build automated SACHET CAP XML feed poller and IMD weather radar alert consumer.
- **Member 3 (Indic NLP & GenAI)**: 
  - Train/fine-tune PyTorch text classifier on Indian disaster posts and package with ONNX Runtime.
- **Member 4 (Drone CV)**: 
  - Train YOLOv8 model for aerial casualty, flood boundary, and fire perimeter detection.
- **Member 5 (Geospatial)**: 
  - Implement spatial clustering algorithms (ST_ClusterDBSCAN) to group duplicate distress calls within a 500m radius.
- **Member 6 (GIS Map UI)**: 
  - Implement interactive incident markers, color-coded severity heatmaps, and spatial boundary overlays.
- **Member 7 (Role Dashboards)**: 
  - Build incident triage queue, verification controls, and multi-agency resource allocation panel.
- **Member 8 (Real-Time & Sync)**: 
  - Implement real-time WebSocket pub/sub broadcasting new incidents and status updates to dispatchers.
- **Member 9 (Compliance & Summarizer)**: 
  - Build automated incident report summarization service generating executive bulletins.
- **Member 10 (DevOps & QA)**: 
  - Implement test database fixtures, automated migration runners, and end-to-end integration tests.

---

### Phase 3: Integration, Sensor Edge & Tactical Responders (Weeks 5 - 6)
*Goal: Connect frontend dashboards to backend APIs, field telemetry, and offline sync.*

- **Member 1 (Architect)**: Oversee system integration drills, API contract enforcement, and cross-service error handling.
- **Member 2 (Gov/Telecom)**: Implement fallback cellular broadcast simulation (SMS/CB-Cell Broadcast mock).
- **Member 3 (Indic NLP & GenAI)**: Implement advisory AI triage service with human-in-the-loop review workflow.
- **Member 4 (Drone CV)**: Build video ingestion pipeline processing aerial surveillance streams.
- **Member 5 (Geospatial)**: Implement routing optimization for emergency rescue vehicles avoiding flood zones.
- **Member 6 (GIS Map UI)**: Implement tactical resource tracking overlay with live GPS vehicle positions.
- **Member 7 (Role Dashboards)**: Build field responder Progressive Web App (PWA) with glove-friendly touch targets.
- **Member 8 (Real-Time & Sync)**: Implement offline IndexedDB storage and background sync for field responders.
- **Member 9 (Compliance & Summarizer)**: Build audit log verification tools confirming SHA-256 tamper-evident integrity.
- **Member 10 (DevOps & QA)**: Build multi-stage Dockerfiles and continuous deployment pipelines (GHCR/Render).

---

### Phase 4: Stress Testing, Fault Injection & Edge Hardening (Weeks 7 - 8)
*Goal: Benchmark high-concurrency performance, simulate telecom failures, and verify audit compliance.*

- **Member 1 (Architect)**: Conduct architecture review, API rate limiting validation, and security audit.
- **Member 2 (Gov/Telecom)**: Validate feed recovery after prolonged simulated upstream service downtime.
- **Member 3 (Indic NLP & GenAI)**: Measure inference latency and optimize throughput under concurrent requests.
- **Member 4 (Drone CV)**: Evaluate computer vision inference accuracy under low-light and adverse weather conditions.
- **Member 5 (Geospatial)**: Optimize spatial query performance with spatial indexing and GiST tuning.
- **Member 6 (GIS Map UI)**: Perform client-side rendering optimizations for rendering 10,000+ simultaneous map entities.
- **Member 7 (Role Dashboards)**: Conduct ergonomics and usability testing under high-stress workflow conditions.
- **Member 8 (Real-Time & Sync)**: Execute connection drop drills: test automatic reconnection and state reconciliation.
- **Member 9 (Compliance & Summarizer)**: Run automated compliance tests against DPDP privacy and PII protection rules.
- **Member 10 (DevOps & QA)**: Execute chaos testing and verify automated zero-downtime container recovery.

---

### Phase 5: End-to-End Simulation Drills & Release Readiness (Weeks 9 - 10)
*Goal: Complete operational disaster response simulations across cyclone, flood, and industrial fire scenarios.*

- **Member 1 (Architect)**: Oversee end-to-end integration test drills, conduct code reviews, and deliver final technical architecture documentation.
- **Member 2 (Gov/Telecom)**: Validate ERSS 112 mock telemetry and SACHET CAP feeds against realistic mock cyclone/flood disaster scenarios.
- **Member 3 (Indic NLP & GenAI)**: Validate triage accuracy on 500+ multi-dialect test samples (including mixed code Hinglish) with >92% F1-score.
- **Member 4 (Drone CV)**: Validate false-positive rejection rates during heavy simulated smoke/rain conditions.
- **Member 5 (Geospatial)**: Verify cluster deduplication accuracy across 1,000 concurrent mock distress points within a 5km radius.
- **Member 6 (GIS Map UI)**: Polish UX micro-interactions, responsive mobile/tablet breakpoints, and visual contrast for bright outdoor field usage.
- **Member 7 (Role Dashboards)**: Complete accessibility (WCAG 2.1 AA) and rapid-click ergonomic testing for stressed field workers with gloves.
- **Member 8 (Real-Time & Sync)**: Conduct simulated telecom blackout drill: verify offline queueing, local sync, and smooth reconnection to central server.
- **Member 9 (Compliance & Summarizer)**: Generate comprehensive executive incident briefing sample reports and verify 100% PII redaction compliance.
- **Member 10 (DevOps & QA)**: Finalize production deployment manifests, automated backup policies, and disaster recovery runbooks.
