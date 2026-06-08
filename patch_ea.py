import re
import sys

with open("MQL5/Experts/InvestmentAI_Executor.mq5", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Comment out CheckForSignals() in OnTimer
content = content.replace("CheckForSignals();", "// CheckForSignals(); // MOVED TO PYTHON EVALUATOR")

# 2. We can just leave the actual functions there but we don't call them, or we can remove them.
# To be safe and clean, let's just leave the functions in the file but since they are not called, they do nothing.
# Wait, actually let's just leave them inside the file, they won't harm anything if they are never called.

with open("MQL5/Experts/InvestmentAI_Executor.mq5", "w", encoding="utf-8") as f:
    f.write(content)

print("EA patched successfully.")
