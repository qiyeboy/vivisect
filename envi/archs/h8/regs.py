from envi.archs.h8.const import *
import envi.registers as e_reg

h8_regs = (
    ('er0', 32),
    ('er1', 32),
    ('er2', 32),
    ('er3', 32),
    ('er4', 32),
    ('er5', 32),
    ('er6', 32),
    ('er7', 32),
    ('pc', 24),
    ('ccr', 8),
)


l = locals()
e_reg.addLocalEnums(l, h8_regs)

CCR_T = 7
CCR_U1= 6
CCR_H = 5
CCR_U0= 4
CCR_N = 3
CCR_Z = 2
CCR_V = 1
CCR_C = 0

ccr_fields = [None for x in range(8)]
for k,v in locals().items():
    if k.startswith('CCR_'):
        ccr_fields[v] = k

H8StatMeta =tuple([
    ("N", REG_FLAGS, CCR_N, 1),
    ("Z", REG_FLAGS, CCR_Z, 1),
    ("C", REG_FLAGS, CCR_C, 1),
    ("V", REG_FLAGS, CCR_V, 1),
    ("U0", REG_FLAGS, CCR_U0, 1),
    ("U1", REG_FLAGS, CCR_U1, 1),
    ("T", REG_FLAGS, CCR_T, 1),
    ("H", REG_FLAGS, CCR_H, 1),
    ])

H8Meta = tuple([
    ('r0', REG_ER0, 0, 16),
    ('e0', REG_ER0, 16, 16),
    ('r0h', REG_ER0, 8, 8),
    ('r0l', REG_ER0, 0, 8),
    ('r1', REG_ER1, 0, 16),
    ('e1', REG_ER1, 16, 16),
    ('r1h', REG_ER1, 8, 8),
    ('r1l', REG_ER1, 0, 8),
    ('r2', REG_ER2, 0, 16),
    ('e2', REG_ER2, 16, 16),
    ('r2h', REG_ER2, 8, 8),
    ('r2l', REG_ER2, 0, 8),
    ('r3', REG_ER3, 0, 16),
    ('e3', REG_ER3, 16, 16),
    ('r3h', REG_ER3, 8, 8),
    ('r3l', REG_ER3, 0, 8),
    ('r4', REG_ER4, 0, 16),
    ('e4', REG_ER4, 16, 16),
    ('r4h', REG_ER4, 8, 8),
    ('r4l', REG_ER4, 0, 8),
    ('r5', REG_ER5, 0, 16),
    ('e5', REG_ER5, 16, 16),
    ('r5h', REG_ER5, 8, 8),
    ('r5l', REG_ER5, 0, 8),
    ('r6', REG_ER6, 0, 16),
    ('e6', REG_ER6, 16, 16),
    ('r6h', REG_ER6, 8, 8),
    ('r6l', REG_ER6, 0, 8),
    ('r7', REG_ER7, 0, 16),
    ('e7', REG_ER7, 16, 16),
    ('r7h', REG_ER7, 8, 8),
    ('r7l', REG_ER7, 0, 8),
])

class H8RegisterContext(e_reg.RegisterContext):
    def __init__(self):
        e_reg.RegisterContext.__init__(self)
        self.loadRegDef(h8_regs)
        self.loadRegMetas(H8Meta, statmetas=H8StatMeta)
        self.setRegisterIndexes(REG_PC, REG_SP)

