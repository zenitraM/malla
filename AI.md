# About AI in this project

Malla was almost entirely kickstarted, or rather _vibe coded_ using AI, with Cursor and Claude 4 Sonnet.

This is a "between jobs hobby project" where I mostly cared about the idea and the UX working and the data making sense, and not so much about the code quality, scalability, security or maintainability.

This means -- this code may likely not what you would call "production ready". I have _not_ gone doing a full review of the entirety of the code the model has churned out, although I at least tried for it to be kept relatively structured.

I also tried the code to make tests that it continously ran (see [cursorrules](./cursorrules)), it was useful to keep a self-running feedback loop but it also likely has led to some of the tests actually being wrong or the AI cheating to make them pass.

I don't think there's a lot of room for it to be security issues in a project like this, the app has no auth, the public facing server only interacts with its own SQLite and most of the data is already public anyhow (if the attacker comes with a LoRA receiver to the right place they can see most of the data). But.. famous last words.

In any case, and just in case - don't run this in production or anywhere close to any critical data if you expose it to the internet, and if you do, take good isolation measures. I run it on a isolated cheap VPS.