# Hindi avatar audition script (expressive, Bulbul v3)

Casting script for the three Hindi avatars (pending item #13, rules in
ADR-014). The moment: bowler runs in → batsman goes for the six →
Suryakumar Yadav takes the catch at long-on.

**How Bulbul v3 expressiveness works (no SSML — do not add tags):**
- Punctuation drives prosody: `,` short pause · `।`/`.` medium pause ·
  `!` emphasis · `…` held breath / trailing off · line break = breathing gap.
- `pace` (0.5–2.0) and `temperature` (0.01–2.0) are API parameters.
- Hindi in Devanagari, English words in Latin. Never romanize Hindi.

**How to audition:** the playground tests voice timbre. For real delivery,
run each segment through the API with the exact `pace` and `temperature`
below — a 10-line Python script; ask Claude for it once the Sarvam key
exists.

---

## Kabir — Delhi Gen Z boy

`model: bulbul:v3 · target_language_code: hi-IN · temperature: 0.85`

| # | pace | Text |
|---|---|---|
| 1 | 1.1 | तो भाई, bowler आ रहा है… गेंद full length पर! |
| 2 | 1.3 | और batsman ने पूरा दम लगा दिया — bat घूमा, गेंद हवा में! ये गई, ये गई, ये गई… |
| 3 | 1.4 | अरे रुको रुको — long-on पर Suryakumar! Catch पकड़ ली भाई! Catch पकड़ ली! |
| 4 | 1.15 | Bro… पूरा scene ही पलट गया। Batsman एकदम cooked — believe नहीं हो रहा उसको! |

Voice target: young male, high energy, natural Hinglish code-switching.

## Naina — Bombay girl

`model: bulbul:v3 · target_language_code: hi-IN · temperature: 0.75`

| # | pace | Text |
|---|---|---|
| 1 | 1.0 | Bowler दौड़ता हुआ आया, गेंद रखी ज़रा full… |
| 2 | 1.15 | और बल्लेबाज़ की आँखों में वही चमक — इरादा सीधा छक्के का! शॉट भी दिल से लगाया, गेंद ऊँची, बहुत ऊँची… |
| 3 | 1.25 | लेकिन long-on पर Suryakumar Yadav! क्या catch है… वाह! |
| 4 | 1.0 | इतनी मेहनत का शॉट, और गया सीधा fielder के हाथों में। Cricket भी ना… एकदम फ़िल्मी है! |

Voice target: female, warm and clear, a smile in the voice.

## Tripathi ji — traditional professional

`model: bulbul:v3 · target_language_code: hi-IN · temperature: 0.5`

| # | pace | Text |
|---|---|---|
| 1 | 0.9 | गेंदबाज़ पूरी लय में… गेंद ज़रा भरी हुई। |
| 2 | 1.05 | बल्लेबाज़ आगे बढ़े, और गगनचुंबी प्रहार! गेंद ऊँची, बहुत ऊँची, लॉन्ग-ऑन की दिशा में… |
| 3 | 1.1 | परन्तु सीमा-रेखा पर सूर्यकुमार यादव — शांत, संतुलित… और लपक लिया! अद्भुत! अद्भुत क्षेत्ररक्षण! |
| 4 | 0.9 | इरादा छक्के का था, परिणाम — पवेलियन की राह। यही तो क्रिकेट की अनिश्चितता है। |

Voice target: mature male, gravitas, measured pace, clean shuddh Hindi.

---

## Why segments, not one block

Each row is one TTS call with its own pace: build-up → strike → climax →
reaction. This is how excitement rises and falls without SSML. In the real
pipeline these segments are the anchored lines from ADR-012, so this
structure costs nothing extra.

## Casting result (fill in)

| Avatar | Bulbul speaker | Notes |
|---|---|---|
| Kabir | _tbd_ | |
| Naina | _tbd_ | |
| Tripathi ji | _tbd_ | |
