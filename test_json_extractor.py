import re
text = "Here is the response:\n```json\n[\"test\"]\n```\nHave a nice day."
match = re.search(r'\[.*\]', text, re.DOTALL)
if match:
    print(match.group(0))
