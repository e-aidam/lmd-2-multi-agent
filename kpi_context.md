# KPI Database Overview

The KPI database is organized around Last Mile Health's community health systems framework:

1. **Strengthen** – Advocate for and build strong community health systems.
2. **Upskill** – Train and grow the community health workforce.
3. **Deliver** – Demonstrate effective community-based primary care.

---

# Table Name Prefixes

| Prefix | Meaning                   |
| ------ | ------------------------- |
| `kpi`  | Key Performance Indicator |
| `lib`  | Liberia                   |
| `eth`  | Ethiopia                  |
| `mlw`  | Malawi                    |
| `sl`   | Sierra Leone              |
| `gs`   | Global Status             |

---

# Acronyms

| Acronym | Definition                                     |
| ------- | --------------------------------------------- |
| AEHO    | Assistant Environmental Health Officer         |
| AFF     | Africa Frontline First                         |
| ARI     | Acute Respiratory Infection                    |
| CBMNC   | Community-Based Maternal and Newborn Care      |
| CHA     | Community Health Assistant                     |
| CHN     | Community Health Nurse                         |
| CHP     | Community Health Promoter                      |
| CHSS    | Community Health Services Supervisor           |
| CHW     | Community Health Worker                        |
| CMA     | Community Midwife Assistant                    |
| eCBIS   | Electronic Community-Based Information System  |
| EHO     | Environmental Health Officer                   |
| FHW     | Frontline Health Worker                        |
| FY      | Fiscal Year (July 1 – June 30)                 |
| HBP     | Health Benefit Package                         |
| HEP     | Health Extension Program                       |
| HEW     | Health Extension Worker                        |
| HSA     | Health Surveillance Assistant                  |
| iCCM    | Integrated Community Case Management           |
| iCHIS   | Integrated Community Health Information System |
| IFI     | Implementation Fidelity Initiative             |
| IRT     | Integrated Refresher Training                  |
| KPI     | Key Performance Indicator                      |
| LMH     | Last Mile Health                               |
| LMS     | Last Mile Survey                               |
| MCD     | Major Communicable Disease                     |
| MERL    | Monitoring, Evaluation, Research, and Learning |
| MOH     | Ministry of Health                             |
| N/A     | Not Applicable                                 |
| NCD     | Non-Communicable Disease                       |

---

# Common Columns

Most KPI tables contain the following metadata fields:

| Column              | Data Type   | Description                         |
| ------------------- | ----------- | ----------------------------------- |
| `id`                | bigint      | Unique row identifier               |
| `date_inserted`     | timestamp   | Date the record was created         |
| `last_update_date`  | timestamp   | Date the record was last modified   |
| `period_start_date` | varchar     | Beginning of the reporting period   |
| `fy_q`              | varchar     | Fiscal year quarter (e.g., FY25 Q1) |

---

# KPI Table Categories

## 1. Strengthen Tables

**Examples**

* `eth_strengthen_1`
* `mlw_strengthen_2`
* `lib_strengthen_1`

**Purpose**

Track activities and outcomes related to strengthening community health systems, including policy development, governance, financing, supervision, supply chains, advocacy, and strategic partnerships.

These indicators align with the **Strengthen** pathway in the Theory of Change, where governments and partners build sustainable systems that support frontline health workers.

**Typical Columns**

| Column                          | Data Type | Description                                                       |
| ------------------------------- | --------- | ----------------------------------------------------------------- |
| `targeted_activity`             | varchar   | An initiative or action being targeted.                          |
| `targeted_activity_summary`     | varchar   | Detailed explanation of the targeted activity.                   |
| `status`                        | varchar   | Current status of the activity (e.g., completed, ongoing).        |
| `progress_update`               | varchar   | Brief progress update on the activity.                           |
| `status_of_blended_irt_modules` | varchar   | Statuses for specific training modules (e.g., RMNCH, NCD).        |

---

## 2. Upskill Tables

**Examples**

* `eth_upskill_1`
* `mlw_upskill_1_2_3`
* `lib_upskill_2`

**Purpose**

Track workforce training, capacity building, and professional development activities for community and frontline health workers.

These indicators align with the **Upskill** pathway in the Theory of Change, where health leaders and frontline workers gain the knowledge and skills needed to deliver high-quality primary care.

**Typical Columns**

| Column                              | Data Type | Description                                                  |
| ----------------------------------- | --------- | ------------------------------------------------------------ |
| `cadre`                             | varchar   | Identifies the job type or role (e.g., nurse, midwife).       |
| `gender`                            | varchar   | Gender composition of the workforce being tracked.           |
| `number_completing_irt_course`      | varchar   | Number completing training during the reporting period.       |
| `number_completing_irt_course_cumulative` | varchar | Cumulative completions across reporting periods.              |

### Metadata

Uses the common columns for metadata (e.g., `id`, `date_inserted`, etc.).

---

## 3. Deliver Tables

**Examples**

* `eth_deliver_1`
* `lib_deliver_1_2_3`
* `mlw_deliver_2`

**Purpose**

Track service delivery outputs and program implementation results achieved through community-based primary care programs.

These indicators align with the **Deliver** pathway in the Theory of Change, which focuses on equitable access to quality care and improved health outcomes.

**Typical Columns**

| Column                            | Data Type | Description                                                  |
| --------------------------------- | --------- | ------------------------------------------------------------ |
| `number_eyeglasses_distributed_ann` | varchar | Number of eyeglasses distributed this fiscal year.           |
| `service-specific utilization`    | varchar   | Metrics vary by service (e.g., treatments provided).          |

---

## 4. Cross-Cutting Tables

**Examples**

* `lib_cross_cutting_1`
* `eth_cross_cutting_2`
* `mlw_cross_cutting_1`

**Purpose**

Track indicators that span multiple domains (Strengthen, Upskill, and Deliver) and provide program-wide measures of reach, scale, and support.

**Typical Columns**

| Column                  | Data Type | Description                                   |
| ----------------------- | --------- | --------------------------------------------- |
| `population_served`     | varchar   | Number of beneficiaries reached.             |
| `population_served_cum_alltime` | varchar | All-time cumulative total.                   |
| `number_supported`      | varchar   | Organizations or facilities supported.       |
| `number_supported_cum_alltime` | varchar | All-time cumulative total for support.       |

---

## 5. Visualization Narrative Tables

**Examples**

* `mlw_vis_narratives`
* `eth_vis_narratives`
* `lib_vis_narratives`

**Purpose**

Store qualitative explanations, contextual information, and reporting narratives associated with KPI performance.

These tables support dashboard visualizations, quarterly reporting, donor reporting, and interpretation of quantitative results.

**Typical Columns**

| Column            | Data Type | Description                                                                |
| ----------------- | --------- | -------------------------------------------------------------------------- |
| `kpi_name`        | varchar   | KPI associated with the narrative.                                         |
| `narrative_long`  | varchar   | Detailed narrative explanation.                                            |
| `narrative_short` | varchar   | Summary narrative for dashboards.                                          |
| `note_1`          | varchar   | First supplemental note.                                                  |
| `note_2`          | varchar   | Second supplemental note.                                                 |
| `variance_status` | varchar   | Indicates whether performance was on target, above target, or below target.|

---

# Relationship to the Theory of Change

| Domain            | Primary Focus                                       | Example Indicators                                                                  |
| ----------------- | --------------------------------------------------- | ----------------------------------------------------------------------------------- |
| **Strengthen**    | Systems, policy, governance, financing, supervision | Program implementation milestones, policy adoption, system strengthening activities |
| **Upskill**       | Workforce training and capacity building            | Number trained, IRT completion, workforce composition                               |
| **Deliver**       | Service delivery and patient reach                  | Services delivered, commodities distributed, patients reached                       |
| **Cross-Cutting** | Program-wide reach and support                      | Population served, beneficiaries supported                                          |
| **Narratives**    | Context and interpretation                          | KPI explanations, progress narratives, variance reporting                           |

