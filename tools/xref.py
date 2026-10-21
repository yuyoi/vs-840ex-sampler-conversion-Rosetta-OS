"""Linear-sweep xref builder.

pickle = (calls, imms, ins, drefs)
  calls: branch/call target -> [sites]
  imms:  32-bit immediate (mov.l/cmp.l #imm...) -> [sites]
  ins:   address -> instruction text
  drefs: absolute memory operand address (@0x...) -> [sites]
"""
import sys, collections, pickle, re
import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from h8sdis import dis
b = open(sys.argv[1], "rb").read(); base = int(sys.argv[3], 16) if len(sys.argv) > 3 else 0x110000; end = base + len(b)
calls = collections.defaultdict(list); imms = collections.defaultdict(list); ins = {}
drefs = collections.defaultdict(list)
BIT = ('btst', 'bset', 'bclr', 'bnot', 'bld', 'bst', 'band', 'bor', 'bxor', 'bil', 'bist', 'biand', 'bior', 'bixor', 'bild')
i = 0x100
while base + i < end:
    n, t, tgt = dis(b, i, base)
    ins[base + i] = t
    if tgt is not None:
        if t.startswith(('jsr', 'bsr', 'jmp', 'b')) and not t.startswith(BIT):
            calls[tgt].append(base + i)
        else:
            imms[tgt].append(base + i)
    for mm in re.finditer(r'@0x([0-9a-f]{6})', t):
        drefs[int(mm.group(1), 16)].append(base + i)
    i += n
pickle.dump((dict(calls), dict(imms), ins, dict(drefs)), open(sys.argv[2], 'wb'))
print('insns', len(ins), 'call targets', len(calls), 'data refs', len(drefs))
