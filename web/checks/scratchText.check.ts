// The scratch pad's export/import format round trip (D326). Run: node --experimental-strip-types web/checks/scratchText.check.ts
import { formatExchange, parseExchange } from "../src/scratchText.ts";
const x = { system: "Be brief.\n\n  indented line", messages: [{ role: "user" as const, content: "Hi\n\nthere" }, { role: "assistant" as const, content: "  Hello. " }] };
const blob = formatExchange(x);
const back = parseExchange(blob);
console.log(JSON.stringify(back) === JSON.stringify(x) ? "roundtrip ok" : "ROUNDTRIP FAIL " + JSON.stringify(back));
console.log(parseExchange("just text") === null ? "plain ok" : "PLAIN FAIL");
console.log(JSON.stringify(parseExchange('[{"role":"system","content":"S"},{"role":"user","content":"u"},{"role":"model","content":"m"}]')));
console.log(JSON.stringify(parseExchange("### User\r\nhey\r\n### MODEL\r\nyo")));
console.log(parseExchange('{"a":1}') === null ? "json-not-list ok" : "FAIL");
