import asyncio

from playwright.async_api import async_playwright

from agent.eligibility import SCHEMES, evaluate, extract_rules, fetch_guideline


async def main():
    scheme = SCHEMES["csss"]
    print(f"Scheme: {scheme['name']}\nSource: {scheme['url']}\n")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        source = await fetch_guideline(browser, scheme["url"])
        await browser.close()
    print(f"Fetched {len(source['text'])} characters at {source['fetched_at']} (sha256 {source['sha256'][:12]}...)\n")

    rules, dropped = await asyncio.to_thread(extract_rules, source)
    print(f"Rules extracted: {len(rules) + len(dropped)} | quote verified: {len(rules)} | dropped: {len(dropped)}")
    for d in dropped:
        print(f"  DROPPED (quote not in source): {d.field} {d.op} {d.value}")

    print("\nEnter your real values (blank = unknown):")
    values = {}
    for field in sorted({r.field for r in rules if r.field != "other"}):
        v = input(f"  {field}: ").strip()
        if v:
            values[field] = v

    verdict, results = evaluate(rules, values)
    print(f"\nVERDICT: {verdict.upper()}\n")
    for r in results:
        mark = {True: "PASS", False: "FAIL", None: "REVIEW"}[r.passed]
        print(f"[{mark:6}] {r.reason}")
        print(f"         source: \"{r.rule.quote[:140]}\"")


if __name__ == "__main__":
    asyncio.run(main())
