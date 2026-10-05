# Legible: speaker script

One to three lines per slide, about 3 minutes in all. Speaking starts on slide 2.
Press **N** in the deck to see the lines. Text in [brackets] is a stage direction, not something to say.

---

## 1 · Opening

[On screen as you walk up. Say nothing; let the title sit.]

## 2 · Why

We spent today with lawyers, and with the people building tools for them. We heard the same thing every time: for all the progress, lawyers still hesitate to let AI summarise a ruling, because the cost is trust.
So we built Legible to make LLMs reliable, by tracing every claim to the voice that made it, and to hand lawyers back their creative work: interpreting the law.

## 3 · The larger problem

Every legal text holds several voices: the court, the court below, the parties.
Lawyers read for who says what. Models flatten it all into one.

## 4 · LLMs get the speaker wrong

A ruling from three weeks ago. We asked what the Court decided, and the answers quote the court of appeal, whose judgment the Court quashed.
Fluent, confident, and in the wrong voice.

## 5 · 19 setups

We asked the same question across 19 setups, from every major lab. 14 got the speaker wrong.
You shouldn't need the biggest model to know who's talking.

## 6 · Our solution

So we built a harness, not another assistant.
Any legal AI runs it behind its answers, and the client only gets what the sources support.

## 7 · How it works

A fast classifier labels every sentence with its speaker, once per ruling. Any LLM answers from that map.
The LLM never decides who's speaking.

## 8 · Live app: ask

Same question, in Legible: the Court didn't rule on this; that's the court of appeal, paragraph 8.
[→] Hover for the source. [→] Click, and you're in the ruling.

## 9 · Live app: check a draft

Paste any AI draft. Every wrong voice is blocked, [→] with a thread to the paragraph that proves it.

## 10 · Benchmarks

Every model we tested goes from red to green.
On rulings it had never seen: 54% to 97%.

## 11 · Trust metrics

Four times fewer misattributions. A confidence on every claim.
And five times cheaper than the biggest model.

## 12 · Built in a day

We built all this in one day: the live app, the harness, and a connector any platform can plug in.
Next: every court, every case file.

## 13 · Close

We don't summarise the ruling for you. We show you who's speaking, so the conclusion stays yours.
[Pause.] Scan it, and try your own ruling.

---

## If asked

- **"Who graded the answers?"** An Opus 5.5 judge with a gold rubric. It agreed 8 out of 8 times with hand grading. The gold answers were written without looking at our pipeline, and a lawyer review is in progress.
- **"Is 97% your best run?"** No, it's the first run, before any change: 113 out of 116. After two fixes it's 115 out of 116.
- **"Does Legora get it wrong?"** Its default agent does. Its frontier options (Opus 5.5, GPT-6 Astra) get it right. We make the default as reliable as the frontier option.
- **"Why not just use the biggest model?"** You can. Haiku with the harness matches Opus 5.5 on this test, about 5× cheaper and 3.5× faster per question.
- **"What does it cost to run?"** Each ruling is labelled once, in about two seconds, and reused for every question. The label model is priced on input only, so it's a small fraction of the answer cost.
