import re

with open("Bot Engine/mt5_connector.py", "r", encoding="utf-8") as f:
    content = f.read()

# Fix open_trade signature
content = content.replace(
    'def open_trade(self, direction, lot_size, sl, tp, symbol=None, comment="AI_BOT") -> Optional[dict]:',
    'def open_trade(self, direction, lot_size, sl, tp, symbol=None, comment="AI_BOT", magic=123456) -> Optional[dict]:'
)

# Fix open_trade body calling place_order
content = content.replace(
    'result = self.place_order(sym, direction, lot_size, sl, tp, comment)',
    'result = self.place_order(sym, direction, lot_size, sl, tp, comment, magic)'
)

# Fix place_order signature
content = content.replace(
    '        comment:  str = "AI_BOT",\n    ) -> dict:',
    '        comment:  str = "AI_BOT",\n        magic:    int = 123456,\n    ) -> dict:'
)

# Fix place_order body
content = content.replace(
    '"magic":         123456,',
    '"magic":         magic,'
)

with open("Bot Engine/mt5_connector.py", "w", encoding="utf-8") as f:
    f.write(content)

# Now update trade_evaluator.py
with open("Bot Engine/trade_evaluator.py", "r", encoding="utf-8") as f:
    content = f.read()

old_trade = 'res_trade = connector.open_trade(action, lot_size, sl=0, tp=0, symbol=sym, comment=f"AI_{style}")'
new_trade = """
            magic_number = 888999
            if style.upper() == "SCALPING": magic_number = 889000
            elif style.upper() == "INTRADAY": magic_number = 889001
            elif style.upper() == "SWING": magic_number = 889002
            
            res_trade = connector.open_trade(action, lot_size, sl=0, tp=0, symbol=sym, comment=f"AI_{style}", magic=magic_number)"""

content = content.replace(old_trade, new_trade)

with open("Bot Engine/trade_evaluator.py", "w", encoding="utf-8") as f:
    f.write(content)

print("Magic numbers patched!")
