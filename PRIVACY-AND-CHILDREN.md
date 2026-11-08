# Privacy and children: engineering requirements

This document turns privacy and children's rights principles into product and release requirements. It is a design aid, not legal advice, a DPIA, or a claim that Family Activity complies with the GDPR or any national law. Before a family release, qualified privacy counsel must assess the actual family use, jurisdictions, product distribution, and each data flow.

## Product purpose and boundaries

Family Activity is intended to help a parent and child understand computer use and have a conversation. It must not become a tool for school attendance decisions, academic or behavioral scoring, advertising, profiling, punishment, or automated restrictions. Reports must distinguish observations from estimates and must never infer intent or misconduct from missing data, unfamiliar networks, or configuration indicators.

The app should remain visible to the child. Setup and the running status indicator should explain what is collected, why, and how to pause or remove monitoring. Parent controls and a child-facing explanation are product safeguards; neither should be represented as legal consent or a substitute for an appropriate legal basis.

## Data currently in scope

The prototype's collection and reporting paths include:

- Foreground application names sampled on the monitored computer.
- Operating-system network-interface byte counters and minimized network configuration indicators. These can be incomplete, overlap, or be unavailable.
- Session, heartbeat, restart, and observable monitoring-gap records.
- A pseudonymous router-change hint where supported; the raw router address is not retained.
- Optional website-domain observations from an experimental Chromium extension installed in a supported browser on the child's computer. It does not collect full URLs, page titles, page content, or private-window domains. It can be paused, removed, disabled, or bypassed by using another browser; missing observations do not explain why.
- Parent-selected schedules and family labels used to produce estimates. These are context supplied by the parent, not proof of where the child or computer was.

The product excludes screenshots, keystrokes, audio, camera, message contents, and automatic blocking. Interface byte totals are not attributed to apps or websites. The Mac setup offers a separate opt-in experimental process-byte summary; it may assign traffic to a helper service, miss short-lived connections, and cannot identify websites. See [README.md](README.md), [FAQ](docs/faq.html), and [ENCRYPTION.md](ENCRYPTION.md) for current implementation detail and limitations.

## Engineering requirements

These requirements translate core GDPR principles into checks for product changes. The legal meaning and applicability of each obligation must still be assessed for the real deployment.

1. **Purpose and lawful basis:** keep processing limited to the disclosed family-understanding purpose. Document the purpose and a proposed legal basis for every collection and sharing path before release; do not assume that parental responsibility by itself resolves every legal question.
2. **Minimize collection:** collect only coarse observations needed for the report. Do not add page contents, full URLs, screenshots, or communications. Keep optional collection genuinely optional and show its status and limits.
3. **Clear notice:** provide a concise, accessible, age-appropriate explanation before collection starts and keep it available afterward. Explain retention, who can open the report, how sharing works, and how to pause, export, or delete data in words children and parents can understand.
4. **Local-first storage:** keep detailed records on the family's devices by default. The child agent encrypts each observation to the parent's public key; this reduces exposure but does not hide all metadata or protect against an administrator on the monitored computer. Reassess privacy and security before adding synchronization, cloud services, analytics, or third-party processors.
5. **Retention and deletion:** use a short, clearly disclosed default retention period and make the setting understandable. Child-side ciphertext has day-granularity expiry metadata so the agent can prune without the parent's private key; an event may therefore be removed up to a day before its selected maximum, and pruning runs on startup and while the agent is running. Existing databases from the previous expiry scheme receive a one-time metadata-only date adjustment without rewriting their encrypted records. Parent-side incoming reports are pruned to the parent's configured window when opened, imported, or shortened. Explain that exported backups are outside those settings and that deleting an app database cannot guarantee removal from backups, filesystem snapshots, or device-level storage remnants. Verify deletion behavior during release validation.
6. **Accuracy and context:** label measured values, estimates, unknowns, and gaps separately. Provide the underlying time range and coverage context. A missing domain sample, agent gap, network hint, or protection indicator must not be presented as proof of a particular cause or behavior.
7. **Child's agency and rights:** invite the child to understand and discuss monitoring in a manner appropriate to their age and maturity. Provide a practical route for the child to see the collection explanation and raise a request to access, correct, or delete information. Do not claim that a parent automatically replaces the child as the data subject or that the child's rights disappear because the device is family-owned.
8. **Security and accountability:** keep the private parent key off the monitored computer; maintain a documented threat model, restricted local access, dependency review, incident/support process, and tested recovery and removal paths. Encryption is one safeguard, not proof of compliance or a complete security guarantee.
9. **Assess high-risk processing:** before release, document whether a data-protection impact assessment is required under GDPR Article 35 and whether consultation with a supervisory authority is needed for unmitigated high residual risk. Do not decide this solely from the fact that storage is local or encrypted.

## Questions for release counsel and privacy review

- Who determines purposes and means in each scenario, and who is the controller or processor? Does the answer change if the product is downloaded from a public website or used on a school-managed device?
- Which lawful basis applies to each data flow, and what balancing or safeguards are needed where a basis such as legitimate interests is considered?
- Does GDPR Article 8 apply to any service offered directly to a child and relying on consent? Its age thresholds concern that specific case and vary by Member State; do not treat it as a universal age-of-digital-consent rule for this parent-installed local tool.
- Which national rules apply where the parent, child, and device are located? Are there additional rules for monitoring in a school, shared household, or another person's account?
- Is a DPIA required, and how should the child's interests, maturity, and opportunity to express their views shape design and review?
- What process, identity checks, response times, and safeguards are appropriate for a child's access, correction, erasure, restriction, or objection request in the intended family context?
- How should the product explain legal rights without suggesting that the software itself determines whether a parent's monitoring is lawful?

Do not assume a household exemption applies. Its scope and the product's role must be evaluated by counsel for each distribution and use model.

## Primary references

- [GDPR, Regulation (EU) 2016/679](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32016R0679), especially Articles 5, 6, 8, 12, 25, 32, and 35, and Recital 38.
- [European Data Protection Board: Children](https://www.edpb.europa.eu/topics/key-gdpr-concepts/children_en), including the expectation that information for children be clear, easy to understand, and age-appropriate.
- [Charter of Fundamental Rights of the European Union, Article 24](https://eur-lex.europa.eu/eli/treaty/char_2016/oj/eng), on the child's best interests and the child's views according to age and maturity.
- [EDPB Guidelines 01/2022 on data subject rights – right of access](https://www.edpb.europa.eu/system/files/2023-04/edpb_guidelines_202201_data_subject_rights_access_v2_en.pdf), relevant to the child's rights as a data subject and representation questions.

## Review status

These requirements are not yet independently reviewed by privacy counsel or tested with families. Completing this document does not close the privacy, children's rights, DPIA, accessibility, or usability release gates in [PLAN.md](PLAN.md).
