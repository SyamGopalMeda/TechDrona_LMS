# Account-Sharing Prevention: How Established Platforms Detect and Prevent Sharing (Input for Tech Drona LMS)

Research date: 2026-11-03. Scope: public documentation, reported behaviour and vendor claims about preventing account sharing, concurrent multi-device use and credential sharing.

Evidence labels used in every bullet:
- **[OFFICIAL]**: the platform's or vendor's own help centre, ToS or docs (verified public documentation).
- **[REPORTED]**: news, third-party blogs, user and community reports (observed or reported behaviour).
- **[VENDOR CLAIM]**: a marketing figure from a vendor about its own product, not independently benchmarked.
- **[UNVERIFIED]** items and anything without a source are in the "Gaps" sections. Recommendations are in the "Inferences" sections and marked **REC**.

Method note: this was a time-boxed search of about 17 tool calls. Many official help pages did not come back in search, so several platform rules rest on secondary sources and are labelled that way. Search-tool summaries were checked against the source where a fetch was possible (Netflix, Cloudflare); otherwise they are reported as the search snippets presented them.

---

## 1. Edtech platforms: device limits, concurrent sessions, ToS sharing clauses

### Takeaway
Of the Indian edtech platforms researched, only Testbook has an official, findable statement that using an account on several devices at once breaks its terms and can get the account blocked. Unacademy (2 web sessions) and Physics Wallah (a new app login logs out the old one) are known only from reports. Global platforms (Coursera, Skillshare, Udemy, LinkedIn Learning) ban sharing in their ToS but publish no numeric device or stream limits that I could find. Across the sector, the usual pattern is "single active session plus a ToS clause plus account blocking," not sophisticated household detection.

### Cited Findings
- **Testbook [OFFICIAL, via search snippet]:** Testbook's help centre article "Account Blocking" says using a SuperCoaching account on several devices at the same time violates its terms and can lead to the account being blocked. It advises users to log out after finishing on a device. — [Testbook Help: Account Blocking](https://intercom.help/testbook-da1e94f5d0c5/en/articles/8123166-account-blocking). Note: a direct fetch of that URL returned HTTP 404 on 2026-11-03, so the article may have moved or been removed. The wording is known only from the search-index snippet.
- **Unacademy [REPORTED, old]:** The Ken reported a policy of "We allow only two web login sessions (desktop browser or mobile browser) per subscriber," with a prompt to log out other devices. The item is roughly 6+ years old. — [The Ken (tag page)](https://the-ken.com/tag/adda-247/). A Quora answer describes signing out older sessions by logging in with OTP, and contacting support to force-terminate sessions. — [Quora](https://www.quora.com/If-I-share-my-Unacademy-subscription-with-someone-how-can-I-make-it-possible-that-he-will-not-use-it-again)
- **Physics Wallah [REPORTED]:** A third-party blog (Primebook, Jan 2025) says logging in to a PW account on a second device's app automatically logs out the first. It also says the website can be used on two devices at once, and the app and the website can run at the same time on different devices. — [Primebook blog](https://www.primebook.in/blog/how-to-use-physics-wallah-app-on-two-devices)
- **PrepInsta:** I found no public device-limit or sharing clause. Its App Store listing shows Prime plans (for example, 3 months at ₹3,999). — [App Store: PrepInsta](https://apps.apple.com/in/app/prepinsta/id6742322105)
- **Comparable edtech ToS pattern [OFFICIAL, different company]:** PREP (prepedu.com, not PrepInsta) reserves the right to suspend accounts showing signs of abuse or sharing, "including login attempts exceeding the permitted number of devices," without stating the number. — [prepedu.com T&C](https://prepedu.com/en/terms-and-conditions-of-transactions)
- **Coursera [OFFICIAL clause, via third-party ToS tracker]:** Users may not "Share your password, let anyone besides yourself access your account, or do anything that might put your account at risk." — [ConductAtlas: Coursera ToU](https://conductatlas.com/platform/coursera/coursera-terms-of-use/prohibition-on-account-sharing-or-compromise/)
- **Skillshare [OFFICIAL clause, via tracker]:** An account must be used by one person only. Sharing the account, login information or access to a membership is prohibited. — [ConductAtlas: Skillshare ToS](https://conductatlas.com/platform/skillshare/skillshare-terms-of-service/account-must-be-used-by-one-person-only/)
- **Udemy [REPORTED, Udemy staff in community forum]:** A community moderator says accounts "cannot be shared between users, as this is considered a violation of our Terms." Third-party sites describe purchases as a personal, non-transferable licence. — [Udemy Community](https://community.udemy.com/en/discussion/159421/how-do-we-set-it-up-so-that-two-people-working-on-different-sites-can-access-one-account). Primary ToS: [udemy.com/terms](https://www.udemy.com/terms/) (not fetched).
- **LinkedIn Learning [OFFICIAL, enterprise terms]:** One seat equals one Customer User, and a seat counts as used once that user registers. — [LinkedIn Learning Usage Terms](https://legal.linkedin.com/linkedinlearning-usage-terms). University guidance adds that the assigned person is the sole user and credentials cannot be shared. — [WVU ITS](https://wvu.atlassian.net/wiki/spaces/ITS/pages/301236419)
- **Pluralsight [REPORTED, institutional]:** A university library notes Pluralsight uses limited licence access, so every person who logs in needs their own assigned licence and account. — [Uni Bielefeld](https://www.ub.uni-bielefeld.de/einrichtungen/bits/services/lul/lernvideos/). Terms: [pluralsight.com/terms](https://pluralsight.com/terms) (sharing clause text not retrieved).
- **Industry framing [REPORTED, vendor]:** VdoCipher's glossary describes concurrent-stream limits and device limits as the typical controls video platforms use. — [VdoCipher: Account Sharing](https://www.vdocipher.com/glossary/account-sharing/)

### Inferences
- In Indian test-prep, the observed norm is "one active app session; a new login kicks out the old one," sometimes plus a small web allowance (Unacademy reportedly allowed 2 web sessions). This is cheap to build and widely accepted by students.
- **REC:** Put an explicit clause in Tech Drona's ToS, modelled on the Coursera and Skillshare wording: one named person per account, no credential sharing, a stated device or session limit, and a graduated consequence ladder (warning, then forced logout, then temporary lock, then suspension). Testbook ties blocking directly to its terms, which gives a clear precedent.
- **REC:** Publish the actual numbers (for example, "2 active sessions, 3 registered devices, 2 device resets per 30 days"). The help pages found for Indian edtech were vague, and vague rules generate support load and disputes.

### Gaps
- I found no official device-limit documentation for **BYJU'S, Vedantu, Adda247, Scaler, PrepInsta or Unacademy** (current). Search returned business and funding coverage only. These need direct checks of each app's help centre or ToS, or a test account.
- The current Testbook article text could not be fetched (404).
- I found no public data on device-reset limits (for example, "you can change your registered device N times") for any edtech platform researched.
- Coursera, Skillshare, Udemy, LinkedIn Learning and Pluralsight concurrent-stream limits: none found publicly.

---

## 2. Streaming and SaaS: what signals they publicly say they use

### Takeaway
Netflix is the clearest public reference. It officially says it determines a "household" from **IP address, device IDs and account activity**, and explicitly does **not** use GPS. Disney+ uses network and device signals with an email one-time-passcode "away from home" flow. Spotify relies on **self-declared address plus re-verification**, not location tracking. Adobe uses a hard **2-activation limit with self-service deactivation**. All of them pair detection with a paid or self-service remedy rather than relying on punitive blocking alone.

### Cited Findings
- **Netflix [OFFICIAL]:** The household is established "based on IP address, device IDs, and account activity." The page also says: "We do not collect GPS data to try to determine the precise physical location of your devices." Sharing outside the household is not allowed. Users can update the household from a TV, review devices on the "manage access and devices" page, and sign out of all devices. — [Netflix Help: What is a Netflix Household?](https://help.netflix.com/en/node/124925) (fetched 2026-11-03)
- **Netflix [REPORTED]:** Early 2023 coverage said devices must connect to home Wi-Fi at least every 31 days. Netflix later told The Streamable that this was posted in error. — via [Fox6](https://fox6now.com/news/netflix-password-sharing-crackdown-details-released) and [Sound & Vision](https://www.soundandvision.com/content/what-you-need-do-netflix-account-sharing-crackdown). Coverage also describes the household as anchored to the most-used Wi-Fi network. — [Mozo](https://mozo.com.au/broadband/articles/all-you-need-to-know-about-netflix-s-crackdown-on-account-sharing)
- **Disney+ [REPORTED, citing Disney help centre]:** Paid sharing launched in 2024. An "Extra Member" costs $6.99/mo (Basic) or $9.99/mo (Premium) in the US. Devices in the same household "would share the same internet connection details regularly." Travellers confirm "I am away from home" or "Update Household" with a one-time passcode sent to the account email. — [Hollywood Reporter](https://www.hollywoodreporter.com/business/business-news/disney-plus-password-sharing-crackdown-begins-paid-sharing-1236011760/); [OTTVerse](https://ottverse.com/disney-launches-paid-sharing-plan-to-tackle-password-sharing/)
- **Spotify Premium Family [OFFICIAL]:** Members must live at the same address. They confirm the address on joining, when the manager's address changes, or when Spotify "can't confirm" it, and are emailed to re-verify. Failure moves the member to the free tier and blocks them from joining any other Family or Duo plan for 12 months. — [Spotify Support: Family address verification](https://support.spotify.com/ca-en/article/family-address-verification/)
- **Spotify [REPORTED, Oct 2026, single source]:** Reports describe a new in-person QR-code check shown from the plan manager's app, and say Spotify states it does not track location for address checks. — [ProPakistani](https://propakistani.pk/2026/10/21/spotify-restricts-family-plan-sharing-similar-to-netflix/amp/). Unconfirmed against Spotify's own pages.
- **Adobe Creative Cloud [REPORTED, university IT KB citing Adobe policy]:** Can be installed on many computers but "activated (i.e., signed in) on two computers at a time," and the apps "can only be actively used on a single computer at a time." Mobile and web use do not count. Signing in on a third computer prompts the user to sign out of one of the others, and devices can be deactivated from the Adobe account. — [U. Michigan KB](https://teamdynamix.umich.edu/TDClient/30/Portal/KB/ArticleDet?ID=14132)
- **Amazon Kindle [REPORTED, conflicting]:** One line of sources says there is no cap on registered devices, and that "six" is a per-title, publisher-set simultaneous-licence limit. Others claim Kindle Unlimited allows up to six registered devices. Kindle Unlimited reportedly allows 10 titles borrowed at a time. — [MobileRead forum](https://www.mobileread.com/forums/showthread.php?p=1188418); [GoodEReader](https://goodereader.com/blog/?p=99907). The sources conflict, so treat this as unresolved.

### Inferences
- The publicly documented signal set at the largest consumer platform (Netflix) is coarse: network (IP), a device identifier and usage patterns. That is enough to build a defensible "primary location plus trusted devices" model without invasive fingerprinting.
- Every mature scheme pairs detection with a **low-friction legitimate path**: OTP for travel (Disney+), self-service device deactivation (Adobe, Netflix), re-verification instead of instant ban (Spotify), or a paid extra seat (Netflix and Disney+).
- **REC (Adobe-style is the best fit for an LMS):** N registered devices (for example, 2 to 3), at most 1 to 2 concurrently *streaming*, a self-service "sign out other devices" page, and a capped number of device swaps per period. This is deterministic, explainable to students and does not depend on fragile IP heuristics.
- **REC:** Consider a "buddy or extra-learner seat" or group discount, the edtech analogue of paid sharing. It turns sharers into revenue rather than only punishing them.

### Gaps
- Netflix and Disney+ thresholds, model logic and false-positive rates are **not public**. Do not assume any specific rule (for example, "31 days" was retracted).
- India-specific Netflix and Disney+ (JioHotstar) household enforcement details were not researched or found.
- Adobe's own help page text was not retrieved. The 2-activation rule is via a university KB and is consistent with many Adobe community posts.

---

## 3. Signals and their reliability

### Takeaway
**IP is a weak identity signal in India.** CGNAT on mobile (Jio, Airtel) and college NATs mean many unrelated users share one IP, and geolocation is coarse (MaxMind's own US city accuracy is about 66% within 50 km, and India is not quoted). **Browser fingerprints are unstable**: they change every few hours to days, though they can be linked probabilistically. **First-party device tokens (cookie, secure storage, app install ID) are the most reliable cheap signal** for counting devices, but users can clear them. Impossible-travel detection needs a learning period and VPN suppression even at Microsoft.

### Cited Findings
**IP and CGNAT**
- **[OFFICIAL, Cloudflare research, Oct 2025]:** A single IPv4 address "may represent hundreds or even thousands of users" because of CGNAT, VPNs and proxies. User-to-IP ratios are highest in parts of Africa and **South Asia**. CGNAT is common on mobile networks. CGNAT IPs are rate-limited about 3x more often than non-CGNAT IPs even though their bot rates are similar (median 4.8% vs 4.7%). Cloudflare built a classifier from over 200K labelled CGNAT IPs (0.98 accuracy) to reduce collateral damage. — [Cloudflare blog: Detecting CGN to reduce collateral damage](https://blog.cloudflare.com/detecting-cgn-to-reduce-collateral-damage/) (fetched 2026-11-03). India is not named specifically.
- **Airtel [REPORTED, 2014]:** Airtel's 3G network ran CGNAT because public IPv4 pools were exhausted. — [Anurag Bhatia blog](https://anuragbhatia.com/2014/10/networking/airtel-3g-running-cgnat/)
- **Jio and Indian ISPs [REPORTED, forum/vendor]:** Jio uses CGN for IPv4 while giving public IPv6. Users report CGNAT on most Indian residential ISPs (for example, ACT). — [TechEnclave](https://techenclave.com/t/act-private-nat-anyone-ever-got-away-from-it/421392?page=2); [PureVPN blog](https://www.purevpn.com/blog/top-isps-using-cgnat/)
- CGNAT shared address space is RFC 6598 100.64.0.0/10 (internal side). Blocking a shared public IP harms innocent co-users. — [Cloudflare](https://blog.cloudflare.com/detecting-cgn-to-reduce-collateral-damage/); [NetworkLessons](https://notes.networklessons.com/carrier-grade-nat)

**IP geolocation**
- **[OFFICIAL, MaxMind]:** For US IPs, about 80% are accurate at state/region level and about 66% at city level (within 50 km). — [MaxMind Support: Geolocation accuracy](https://support.maxmind.com/hc/en-us/articles/4407630607131). Per-country figures, including India, are on [MaxMind accuracy comparison](https://www.maxmind.com/en/geoip-accuracy-comparison), but the India row was not retrieved.
- **[OFFICIAL, MaxMind 2016]:** Release notes claim "significantly improved accuracy" for countries outside the US, especially China, India and Japan (no number given). — [MaxMind release notes 2016](https://dev.maxmind.com/geoip/release-notes/2016?lang=en)
- **[REPORTED]:** Users report low MaxMind accuracy in India. A Wikimedia test shows mixed results for Indian IPs, with some matches within 12 to 20 km and some in the wrong city. — [Amplitude community](https://community.amplitude.com/product-personalization-and-audience-segmentation-70/which-all-paraments-can-i-use-to-capture-city-information-like-i-want-to-groupby-by-cities-to-find-my-orders-at-a-city-level-any-alternative-to-ip-based-city-2597); [Wikimedia MaxMindCityTesting](https://meta.wikimedia.org/wiki/MaxMindCityTesting)

**Browser fingerprinting**
- **[ACADEMIC] FP-STALKER (Vastel, Laperdrix, Rudametkin, Rouvoy, IEEE S&P 2018):** Fingerprints change frequently, "from every few hours to days," because of software updates and configuration changes. On 98,598 fingerprints from 1,905 browser instances over 2 years, browsers could be linked across changes for 54.48 days on average, and 26% for more than 100 days. — [HAL: FP-STALKER](https://hal.archives-ouvertes.fr/hal-01652021); [IEEE](https://ieeexplore.ieee.org/document/8418634/)
- **[ACADEMIC summary]:** Fingerprints show "relatively high statistical uniqueness" (Laperdrix 2016, "Beauty and the Beast," IEEE S&P 2016) but are unstable. — [LIG lab summary](https://www.liglab.fr/en/node/795)
- **FingerprintJS open source vs Pro [VENDOR CLAIM]:** Fingerprint says Pro identifies returning visitors with 99.5% accuracy even when the IP changes, defining accuracy as the share of returning visitors correctly recognised as returning. The open-source library is described as significantly less accurate (vendor tables say "up to 60%"). The often-quoted "40–60%" figure appears on GitHub and community pages, not as a published benchmark. — [Fingerprint FAQ](https://fingerprintJS.com/resources/frequently-asked-questions-faqs/); [GitHub topic](https://Github.com/topics/fingerprintjs). No independent benchmark found.

**Impossible travel**
- **Microsoft Entra ID Protection [OFFICIAL]:** "Atypical travel" is an offline Premium detection that flags two sign-ins from geographically distant locations where at least one location may also be atypical for the user. "Impossible travel" is sourced from Defender for Cloud Apps. — [Microsoft Learn: Risk detections](https://learn.microsoft.com/en-us/entra/id-protection/concept-identity-protection-risks)
- **Microsoft [REPORTED, Microsoft moderator on Q&A]:** There is an initial learning period of "the earliest of 14 days or 10 logins." The algorithm ignores obvious false positives such as VPNs and locations regularly used by other users in the organisation. — [Microsoft Q&A](https://learn.microsoft.com/en-us/answers/questions/768911/atypical-travel-unfamiliar-sign-in-properties)
- **[REPORTED]:** Security vendors document impossible-travel false positives caused by cloud proxies and NAC services egressing from distant IPs. — [Portnox KB](https://doc.portnox.com/topics/kb_entra_impossible_travel)

### Inferences
- Signal reliability ranking for an Indian LMS (my assessment, not sourced):
  1. **Concurrent authenticated streams or sessions** (server-side fact, unambiguous).
  2. **First-party device token** (random ID in a secure cookie, localStorage or app keystore; stable until the user clears it).
  3. **Device or OS attributes and user-agent client hints** (coarse, good for labelling devices in a "your devices" UI).
  4. **Browser fingerprint** (useful for re-linking after a cookie clear; drifts within days).
  5. **IP / ASN** (useful to distinguish "same Wi-Fi" from "different network," but CGNAT makes "same IP" weak evidence of same household and "different IP" very weak evidence of a different person, since mobile users rotate IPs).
  6. **IP geolocation** (country is reliable; city in India is unreliable).
- Impossible travel based on IP geolocation will **false-positive heavily in India**, because mobile CGNAT egress points can geolocate to a different city than the user. Microsoft itself needs a learning period and VPN suppression.
- **REC:** Never block on a single IP or geolocation event. Use IP and geolocation only as a contributing score, weighted by ASN type (mobile carrier or CGNAT = low weight; hosting/VPN = flag; fixed broadband = medium).
- **REC:** The strongest sharing evidence is **simultaneous active sessions (overlapping lesson playback or test-taking) on 2+ distinct device tokens, from distinct networks, repeatedly over days**. That is behavioural overlap, not a single signal.

### Gaps
- **[UNVERIFIED]** The India row of MaxMind's accuracy table was not retrieved. Get it from the MaxMind page directly.
- **[UNVERIFIED]** I found no authoritative public statistic on the share of Jio or Airtel users behind CGNAT, or on IPv6 adoption share, in this session.
- **[NOT RESEARCHED IN THIS SESSION]** The EFF Panopticlick (Eckersley, "How Unique Is Your Web Browser?", PETS 2010) and AmIUnique (Laperdrix et al. 2016) uniqueness figures, and Gómez-Boix et al. 2018 ("Hiding in the Crowd," WWW 2018, which found much lower uniqueness on a large real-world dataset). Their numbers should be pulled from the papers before citing.
- **[NOT RESEARCHED]** Okta and Google impossible-travel or suspicious-login documentation; User-Agent Client Hints spec details (W3C/WICG) and Chrome UA reduction; Safari and Firefox anti-fingerprinting effects on stability.
- College or hostel NAT prevalence: no data found.

---

## 4. Commercial services: capabilities and pricing

### Takeaway
Device-intelligence and IP-risk APIs are available at low entry cost (free tiers of roughly 1,000 calls per month are common), but almost all pricing found came from **secondary or competitor pages**, so it must be re-checked on vendor sites. For an LMS of Tech Drona's scale, an IP-type/VPN lookup plus first-party device tokens is likely enough before paying for full device fingerprinting.

### Cited Findings
- **Fingerprint (Pro) [REPORTED pricing]:** Free tier reported as 1,000 API calls/month by one source and 20,000 by another (conflicting). Pro Plus about $99/mo for 20,000 calls. Overage about $4 per 1,000. Enterprise is custom. — [AbstractAPI: Fingerprint alternatives](https://www.abstractapi.com/guides/alternatives-to/fingerprint-alternatives); [G2: Fingerprint pricing](https://www.g2.com/products/fingerprintjs-fingerprint/pricing). Capability: visitor ID that survives IP changes (99.5% accuracy is a [VENDOR CLAIM](https://fingerprintJS.com/resources/frequently-asked-questions-faqs/)).
- **Castle.io [REPORTED, competitor page, Q3 2023]:** Professional $33/mo (10,000 calls) and Enterprise $2,800/mo, with nothing in between. — [SEON vs Castle comparison](https://seon.io/resources/comparisons/compare-seon-vs-castle-io/). Castle has since announced "unbundling," with IP intelligence as a standalone product. — [Castle blog](https://blog.castle.io/were-unbundling-castle-and-ip-intelligence-is-the-first-piece/)
- **SEON [REPORTED]:** Vendor-published comparisons claim a free tier and a 14-day trial (2023). A 2026 third-party table lists "contact sales." Sources conflict. — [SEON comparison](https://seon.io/resources/comparisons/compare-seon-vs-castle-io/); [Stork.ai](https://www.stork.ai/alternatives/seon)
- **IPQualityScore [REPORTED]:** Free tier of 1,000 lookups/month (consistent across sources). Paid entry reported at $99/mo by one source. Residential-proxy detection reportedly needs SMB+ (about $999/mo). — [Postmake](https://postmake.io/tools/ipqualityscore); [ipgeolocation.io comparison](https://ipgeolocation.io/blog/what-are-the-best-vpn-and-proxy-detection-apis.md)
- **IPinfo privacy detection [REPORTED]:** Detects VPN, Tor, proxy, relay (including iCloud Private Relay) and residential proxy. Free tier reportedly limited to country-level data in 2025. Privacy detection reportedly from $49/mo for 150k requests (not confirmed officially). — [Codersera 2026 guide](https://codersera.com/blog/how-to-detect-vpn-users-on-your-website/amp/)

### Inferences
- **REC:** Phase 1 should use no paid fingerprinting: first-party device tokens plus server-side session tracking, with an IP-type lookup (hosting/VPN/mobile) from a cheap tier (IPinfo, IPQS free, or a MaxMind GeoLite/ASN database). Phase 2 should add Fingerprint Pro or Castle only if Phase 1 data shows cookie-clearing evasion at meaningful scale.
- These vendors are built for **fraud and account-takeover**, not edtech sharing. Their scores (for example, "risky IP") will flag many legitimate Indian mobile users and should not be used as direct ban triggers.

### Gaps
- **[NOT RESEARCHED]** Sift and MaxMind minFraud capabilities and pricing were not retrieved in this session.
- None of the pricing above was confirmed on an official vendor pricing page. Re-verify before budgeting.
- No vendor publishes false-positive rates specific to Indian mobile traffic.

---

## 5. Account-sharing detection approaches, false positives and appeal flows

### Takeaway
The publicly documented consumer approaches are rule-based: a concurrency cap, a registered-device cap, a household or network anchor, and a verification step (OTP or re-verify) instead of instant punishment. Academic work suggests fingerprints can be re-linked over time, but **I found no peer-reviewed paper specifically on edtech account-sharing detection** in this session. Appeal and recovery flows (OTP "I'm travelling," self-service device removal, re-verification windows) are an explicit part of every major scheme found.

### Cited Findings
- **Verification instead of block [OFFICIAL/REPORTED]:** Disney+ uses an email OTP for "away from home" ([OTTVerse](https://ottverse.com/disney-launches-paid-sharing-plan-to-tackle-password-sharing/)). Spotify sends a re-verify email with a time window, and failure means a downgrade, not account deletion ([Spotify Support](https://support.spotify.com/ca-en/article/family-address-verification/)). Netflix provides household update and "sign out of all devices" ([Netflix Help](https://help.netflix.com/en/node/124925)).
- **Self-service device management [REPORTED]:** Adobe prompts users to sign out of one of the existing devices when activating a third. — [U. Michigan KB](https://teamdynamix.umich.edu/TDClient/30/Portal/KB/ArticleDet?ID=14132)
- **False positives in the household-IP approach [REPORTED, low-quality sources]:** IP geolocation inaccuracy, Wi-Fi changes, device mobility and VPNs can cause false "outside household" detections. — [Autodesk-hosted article](https://origin-exchange.autodesk.com/how-to-overcome-netflix-household-issue); [Cheapies.nz user reports](https://www.cheapies.nz/node/46528)
- **Fingerprint linkage over time [ACADEMIC]:** FP-STALKER shows rule-based and ML linkage of evolving fingerprints, giving 54.48 days average tracking. This is a building block for a device-account graph. — [HAL](https://hal.archives-ouvertes.fr/hal-01652021)
- **Collateral damage from shared-IP enforcement [OFFICIAL, Cloudflare]:** Treating a shared IP as one actor penalises many innocent users. Cloudflare explicitly builds CGNAT detection to soften mitigations. — [Cloudflare](https://blog.cloudflare.com/detecting-cgn-to-reduce-collateral-damage/)
- **Edtech precedent for hard blocking [OFFICIAL, via snippet]:** Testbook says multi-device simultaneous use may lead to the account being blocked. — [Testbook Help](https://intercom.help/testbook-da1e94f5d0c5/en/articles/8123166-account-blocking)

### Inferences (detection design, REC)
- **REC: risk score built from features (each weak alone):**
  - (a) Concurrent overlap: 2+ device tokens with overlapping playback or test sessions within the same minutes.
  - (b) Distinct device count over 30 days above the limit.
  - (c) Distinct "network clusters" (ASN plus /24, or a city cluster) used concurrently.
  - (d) Same account active in two cities more than about 300 km apart within a short window, low weight given CGNAT.
  - (e) Behavioural divergence: different course progress patterns, typing or test-answer timing, or language preference per device.
  - (f) Device-account graph: one device token logging into many accounts (a "shared login PC" or credential reseller), or one account appearing on many devices.
  - (g) Credential-reseller signals: account accessed from hosting or VPN ASNs, or many logins on fresh device tokens.
- **REC: graduated response:**
  1. Soft notice ("You're logged in on another device—continue here?").
  2. Force-logout of the older session (the PW and Unacademy pattern).
  3. Step-up OTP to the registered phone or email, which is cheap in India via SMS/WhatsApp and directly targets credential sharing because the sharer must hand over an OTP each time.
  4. Temporary lock after repeated high scores.
  5. Human review before suspension, with an in-app appeal form.
- **REC:** Treat placement-test and mock-interview sessions differently from video viewing. A shared account during an assessment corrupts that user's placement-readiness data, which justifies stricter concurrency there.
- **REC:** Log every enforcement decision with the contributing signals so an appeal reviewer, and the user under India's DPDP Act notice obligations, can see why. Do not auto-ban on IP or fingerprint alone.

### Gaps
- No academic paper specifically on account-sharing detection (session overlap or co-usage graph) was retrieved in this session. Literature on streaming-account sharing (for example, Netflix-adjacent or IEEE/ACM work on credential sharing) needs a dedicated search.
- No public false-positive or appeal-rate statistics from any platform were found.
- DPDP Act 2023 or Rules obligations for device fingerprinting consent were not researched here.

---

## 6. Watermarking and content protection as a sharing deterrent

### Takeaway
DRM (Widevine and FairPlay) stops downloading and casual ripping, and a **dynamic, user-specific watermark** (user ID, email or phone flashing across the video) is the standard deterrent for screen or camera capture. VdoCipher, an Indian-origin vendor, markets this combination heavily to edtech. User-ID watermarks need a backend or API integration, not a plain iframe embed.

### Cited Findings
- **VdoCipher [VENDOR CLAIM]:** "DRM blocks downloading, and the watermark deters and traces the capture routes DRM cannot close." It provides Widevine for Android, Windows and Chrome, and FairPlay for iOS and Safari. — [VdoCipher DRM page](https://www.vdocipher.com/page/drm/); [VdoCipher Dynamic Watermarking](https://www.vdocipher.com/dynamic-watermarking/)
- **User-based dynamic watermark [REPORTED, 2021 product showcase]:** The watermark can show user email, user ID, IP or a timestamp. Screen capture can be blocked in mobile apps; on websites the watermark is used instead. — [Help Net Security](https://www.helpnetsecurity.com/2021/08/11/product-showcase-vdocipher/)
- **Integration caveat [OFFICIAL, VdoCipher]:** Iframe integration can show IP and text as a watermark but "can not show user id, email id etc. since it is not a backend integration." — [VdoCipher subtitle/integration page](https://vdocipher.com/subtitle/)
- **Pricing [VENDOR CLAIM]:** DRM, dynamic watermark, analytics and mobile SDKs on every plan "from $149/year." — [VdoCipher vs Gumlet](https://www.vdocipher.com/gumlet-alternative/)
- **Moving watermark [VENDOR, 2015]:** A user-specific watermark that "moves continuously" and flashes every few seconds. — [VdoCipher blog](https://www.vdocipher.com/blog/2015/04/how-got-video-leak-could-have-been-prevented-with-vdocipher/)

### Inferences
- The watermark is more relevant to *content leakage* (recordings resold on Telegram) than to *account sharing*. However, a visible "Registered to: name / phone" overlay also discourages handing a login to friends, because the sharer's identity is printed on everything they watch.
- **REC:** Use a DRM video host (VdoCipher, Gumlet or Mux) with server-side token generation, so each playback token embeds the user ID plus a session ID. Overlay name and masked phone dynamically. Enable FLAG_SECURE / screen-capture blocking in the Android app. Tie concurrent-stream limits to playback-token issuance: refuse a new token if N active tokens already exist for the account. This doubles as the most reliable concurrency enforcement point.

### Gaps
- **[NOT RESEARCHED]** Gumlet's and Mux's watermarking and DRM feature and pricing specifics. The Mux DRM product status in 2026 was not checked.
- No independent evidence was found on watermark effectiveness against phone-camera recording, or on which Indian edtechs (PW, Unacademy, etc.) publicly use which vendor.
- No Indian news coverage of edtech video piracy (Telegram leaks) was retrieved in this session.
