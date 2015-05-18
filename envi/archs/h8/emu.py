"""
The H8 Emulator module.
"""

import struct

import envi
from envi.archs.h8 import H8Module
from envi.archs.h8.regs import *

# CPU Operating Modes:  
#   Normal      64kb RAM, program and data areas combined
#       E0-E7 (extended regs) can be used as 16bit or combined with R0-R7 for 32bit data regs
#           when used as 16bit reg it can contain any value, even when corrsponding R# reg is used as an address reg.
#           if the general reg is ref'd in reg indir adr mode with pre-dec or post-inc and carry/borrow occurs, the value in corrsponding register will be affected.
#       Instruction Set - all instrs/modes of H8-300 can be used.  if 24bit ea (effective address) is used, only lower 16bits used
#       Exception Vector Table/MemIndirBranchAddress - top area starting at H'0000 is exception vector table.  16bit branch addrs
#           differs by mcu, see mcu hardware manual for further info           
#       Stack Structure - when the PC is pushed on stack in subroutine call, and PC and CCR are pushed on stack in exception handling, they are stored the same as H8/300

#   Advanced    16mb RAM, program and data areas combined
#       E0-E7 - same.  when used as 24bit, upper 8bits are ignored.
#       Instruction Set - All additioncl instrs/addrmodes of H8/300H 
#       Exception Vector Table - top H'000000 is exception vector table in units of 32bits.  upper 8 bits ignored.  H'000000-H'0000FF
#       Stack Structure - when PC is stored on stack, stored as 32bits. when PC and CCR, CCR fills that upper 8 bits.

# calling conventions
class H8ArchitectureProcedureCall(envi.CallingConvention):
    """
    Implement calling conventions for your arch.
    """
    def execCallReturn(self, emu, value, ccinfo=None):
        sp = emu.getRegister(REG_SP)
        pc = struct.unpack(">H", emu.readMemory(sp, 2))[0]
        sp += 2 # For the saved pc
        sp += (2 * argc) # Cleanup saved args

        emu.setRegister(REG_SP, sp)
        emu.setRegister(REG_R0, value)
        emu.setProgramCounter(pc)

    def getCallArgs(self, emu, count):
        return emu.getRegisters(0xf)  # r0-r3 are used to hand in parameters.  additional ph8s are stored and pointed to by r0

aapcs = H8ArchitectureProcedureCall()


class H8Emulator(H8Module, H8RegisterContext, envi.Emulator):

    def __init__(self):
        H8Module.__init__(self)

        self.coprocs = [CoProcEmulator() for x in xrange(16)]       # FIXME: this should be None's, and added in for each real coproc... but this will work for now.

        seglist = [ (0,0xffffffff) for x in xrange(6) ]
        envi.Emulator.__init__(self, H8Module())

        H8RegisterContext.__init__(self)

        self.addCallingConvention("H8 Arch Procedure Call", aapcs)

    def undefFlags(self):
        """
        Used in PDE.
        A flag setting operation has resulted in un-defined value.  Set
        the flags to un-defined as well.
        """
        self.setRegister(REG_EFLAGS, None)

    def setFlag(self, which, state):
        flags = self.getRegister(REG_FLAGS)
        if state:
            flags |= which
        else:
            flags &= ~which
        self.setRegister(REG_FLAGS, flags)

    def getFlag(self, which):
        flags = self.getRegister(REG_FLAGS)
        if flags == None:
            raise envi.PDEUndefinedFlag(self)
        return bool(flags & which)

    def readMemValue(self, addr, size):
        bytes = self.readMemory(addr, size)
        if bytes == None:
            return None
        if len(bytes) != size:
            raise Exception("Read Gave Wrong Length At 0x%.8x (va: 0x%.8x wanted %d got %d)" % (self.getProgramCounter(),addr, size, len(bytes)))
        if size == 1:
            return struct.unpack("B", bytes)[0]
        elif size == 2:
            return struct.unpack(">H", bytes)[0]
        elif size == 4:
            return struct.unpack(">L", bytes)[0]
        elif size == 8:
            return struct.unpack(">Q", bytes)[0]

    def writeMemValue(self, addr, value, size):
        #FIXME change this (and all uses of it) to passing in format...
        #FIXME: Remove byte check and possibly half-word check.  (possibly all but word?)
        if size == 1:
            bytes = struct.pack("B",value & 0xff)
        elif size == 2:
            bytes = struct.pack(">H",value & 0xffff)
        elif size == 4:
            bytes = struct.pack(">L", value & 0xffffffff)
        elif size == 8:
            bytes = struct.pack(">Q", value & 0xffffffffffffffff)
        self.writeMemory(addr, bytes)

    def readMemSignedValue(self, addr, size):
        #FIXME: Remove byte check and possibly half-word check.  (possibly all but word?)
        bytes = self.readMemory(addr, size)
        if bytes == None:
            return None
        if size == 1:
            return struct.unpack("b", bytes)[0]
        elif size == 2:
            return struct.unpack(">h", bytes)[0]
        elif size == 4:
            return struct.unpack(">l", bytes)[0]

    def executeOpcode(self, op):
        # NOTE: If an opcode method returns
        #       other than None, that is the new pc
        x = None
        meth = self.op_methods.get(op.mnem, None)
        if meth == None:
            raise envi.UnsupportedInstruction(self, op)
        x = meth(op)
        print >>sys.stderr,"executed instruction, returned: %s"%x

        if x == None:
            pc = self.getProgramCounter()
            x = pc+op.size

        self.setProgramCounter(x)

    def doPush(self, val):
        sp = self.getRegister(REG_SP)
        sp -= 2
        self.writeMemValue(sp, val, 2)
        self.setRegister(REG_SP, sp)

    def doPop(self):
        sp = self.getRegister(REG_SP)
        val = self.readMemValue(sp, 2)
        self.setRegister(REG_SP, sp+2)
        return val

    def integerSubtraction(self, op):
        """
        Do the core of integer subtraction but only *return* the
        resulting value rather than assigning it.
        (allows cmp and sub to use the same code)
        """
        # Src op gets sign extended to dst
        #FIXME account for same operand with zero result for PDE
        src1 = self.getOperValue(op, 1)
        src2 = self.getOperValue(op, 2)

        if src1 == None or src2 == None:
            self.undefFlags()
            return None

        return self.intSubBase(src1, src2, Sflag)

    def intSubBase(self, src1, src2, Sflag=0, rd=0):
        # So we can either do a BUNCH of crazyness with xor and shifting to
        # get the necessary flags here, *or* we can just do both a signed and
        # unsigned sub and use the results.


        usrc = e_bits.unsigned(src1, 4)
        udst = e_bits.unsigned(src2, 4)

        ssrc = e_bits.signed(src1, 4)
        sdst = e_bits.signed(src2, 4)

        ures = udst - usrc
        sres = sdst - ssrc

        if Sflag:
            curmode = self.getProcMode() 
            if rd == 15:
                if(curmode != PM_sys and curmode != PM_usr):
                    self.setCPSR(self.getSPSR(curmode))
                else:
                    raise Exception("Messed up opcode...  adding to r15 from PM_usr or PM_sys")
            self.setFlag(PSR_C, e_bits.is_unsigned_carry(ures, 4))
            self.setFlag(PSR_Z, not ures)
            self.setFlag(PSR_N, e_bits.is_signed(ures, 4))
            self.setFlag(PSR_V, e_bits.is_signed_overflow(sres, 4))

        #print "s2size/s1size: %d %d" % (s2size, s1size)
        #print "unsigned: %d %d %d" % (usrc, udst, ures)
        #print "signed: %d %d %d" % (ssrc, sdst, sres)
        
        #if Sflag:
        #    self.setFlag(PSR_N, sres>>32)
        #    self.setFlag(PSR_Z, sres==0)
        #    self.setFlag(PSR_C, e_bits.is_unsigned_carry(ures, s2size))
        #    self.setFlag(PSR_V, e_bits.is_signed_overflow(sres, s2size))

        return ures


    def logicalAnd(self, op):
        src1 = self.getOperValue(op, 1)
        src2 = self.getOperValue(op, 2)

        # PDE
        if src1 == None or src2 == None:
            self.undefFlags()
            self.setOperValue(op, 0, None)
            return

        res = src1 & src2

        self.setFlag(PSR_N, 0)
        self.setFlag(PSR_V, 0)
        self.setFlag(PSR_C, 0)
        self.setFlag(PSR_Z, not res)
        return res

    def i_and(self, op):
        res = self.logicalAnd(op)
        self.setOperValue(op, 0, res)
        
    def i_stm(self, op):
        srcreg = self.getOperValue(op,0)
        regmask = self.getOperValue(op,1)
        pc = self.getRegister(REG_PC)       # store for later check

        start_address = self.getRegister(srcreg)
        addr = start_address
        for reg in xrange(16):
            if reg in regmask:
                val = self.getRegister(reg)
                if op.iflags & IF_DAIB_B:
                    if op.iflags & IF_DAIB_I:
                        addr += 4
                    else:
                        addr -= 4
                    self.writeMemValue(addr, val, 4)
                else:
                    self.writeMemValue(addr, val, 4)
                    if op.iflags & IF_DAIB_I:
                        addr += 4
                    else:
                        addr -= 4
                if op.opers[0].oflags & OF_W:
                    self.setRegister(srcreg,addr)
        #FIXME: add "shared memory" functionality?  prolly just in strex which will be handled in i_strex
        # is the following necessary?  
        newpc = self.getRegister(REG_PC)    # check whether pc has changed
        if pc != newpc:
            return newpc

    i_stmia = i_stm


    def i_ldm(self, op):
        srcreg = self.getOperValue(op,0)
        regmask = self.getOperValue(op,1)
        pc = self.getRegister(REG_PC)       # store for later check

        start_address = self.getRegister(srcreg)
        addr = start_address
        for reg in xrange(16):
            if reg in regmask:
                if op.iflags & IF_DAIB_B:
                    if op.iflags & IF_DAIB_I:
                        addr += 4
                    else:
                        addr -= 4
                    regval = self.readMemValue(addr, 4)
                    self.setRegister(reg, regval)
                else:
                    regval = self.readMemValue(addr, 4)
                    self.setRegister(reg, regval)
                    if op.iflags & IF_DAIB_I:
                        addr += 4
                    else:
                        addr -= 4
                if op.opers[0].oflags & OF_W:
                    self.setRegister(srcreg,addr)
        #FIXME: add "shared memory" functionality?  prolly just in ldrex which will be handled in i_ldrex
        # is the following necessary?  
        newpc = self.getRegister(REG_PC)    # check whether pc has changed
        if pc != newpc:
            return newpc

    i_ldmia = i_ldm

    def i_ldr(self, op):
        # hint: covers ldr, ldrb, ldrbt, ldrd, ldrh, ldrsh, ldrsb, ldrt   (any instr where the syntax is ldr{condition}stuff)
        val = self.getOperValue(op, 1)
        self.setOperValue(op, 0, val)
        if op.opers[0].reg == REG_PC:
            return val





    def i_add(self, op):
        src1 = self.getOperValue(op, 1)
        src2 = self.getOperValue(op, 2)
        
        #FIXME PDE and flags
        if src1 == None or src2 == None:
            self.undefFlags()
            self.setOperValue(op, 0, None)
            return

        dsize = op.opers[0].tsize
        ssize = op.opers[1].tsize
        s2size = op.opers[2].tsize

        usrc1 = e_bits.unsigned(src1, 4)
        usrc2 = e_bits.unsigned(src2, 4)
        ssrc1 = e_bits.signed(src1, 4)
        ssrc2 = e_bits.signed(src2, 4)

        ures = usrc1 + usrc2
        sres = ssrc1 + ssrc2


        self.setOperValue(op, 0, ures)

        curmode = self.getProcMode() 
        if op.flags & IF_S:
            if op.opers[0].reg == 15 and (curmode != PM_sys and curmode != PM_usr):
                self.setCPSR(self.getSPSR(curmode))
            else:
                raise Exception("Messed up opcode...  adding to r15 from PM_usr or PM_sys")
            self.setFlag(PSR_C, e_bits.is_unsigned_carry(ures, dsize))
            self.setFlag(PSR_Z, not ures)
            self.setFlag(PSR_N, e_bits.is_signed(ures, dsize))
            self.setFlag(PSR_V, e_bits.is_signed_overflow(sres, dsize))

    def i_b(self, op):
        return self.getOperValue(op, 0)

    def i_bl(self, op):
        self.setRegister(REG_LR, self.getRegister(REG_PC))
        return self.getOperValue(op, 0)

    def i_tst(self, op):
        src1 = self.getOperValue(op, 0)
        src2 = self.getOperValue(op, 1)

        dsize = op.opers[0].tsize
        ures = src1 & src2

        self.setFlag(PSR_N, e_bits.is_signed(ures, dsize))
        self.setFlag(PSR_Z, (0,1)[ures==0])
        self.setFlag(PSR_C, e_bits.is_unsigned_carry(ures, dsize))
        #self.setFlag(PSR_V, e_bits.is_signed_overflow(sres, dsize))
        
    def i_rsb(self, op):
        src1 = self.getOperValue(op, 1)
        src2 = self.getOperValue(op, 2)
        
        #FIXME PDE and flags
        if src1 == None or src2 == None:
            self.undefFlags()
            self.setOperValue(op, 0, None)
            return

        dsize = op.opers[0].tsize
        ssize = op.opers[1].tsize
        s2size = op.opers[2].tsize

        usrc1 = e_bits.unsigned(src1, 4)
        usrc2 = e_bits.unsigned(src2, 4)
        ssrc1 = e_bits.signed(src1, 4)
        ssrc2 = e_bits.signed(src2, 4)

        ures = usrc2 - usrc1
        sres = ssrc2 - ssrc1


        self.setOperValue(op, 0, ures)

        curmode = self.getProcMode() 
        if op.flags & IF_S:
            if op.opers[0].reg == 15:
                if (curmode != PM_sys and curmode != PM_usr):
                    self.setCPSR(self.getSPSR(curmode))
                else:
                    raise Exception("Messed up opcode...  adding to r15 from PM_usr or PM_sys")
            self.setFlag(PSR_C, e_bits.is_unsigned_carry(ures, dsize))
            self.setFlag(PSR_Z, not ures)
            self.setFlag(PSR_N, e_bits.is_signed(ures, dsize))
            self.setFlag(PSR_V, e_bits.is_signed_overflow(sres, dsize))

    def i_rsb(self, op):
        # Src op gets sign extended to dst
        #FIXME account for same operand with zero result for PDE
        src1 = self.getOperValue(op, 1)
        src2 = self.getOperValue(op, 2)
        Sflag = op.iflags & IF_PSR_S

        if src1 == None or src2 == None:
            self.undefFlags()
            return None

        res = self.intSubBase(src2, src1, Sflag, op.opers[0].reg)
        self.setOperValue(op, 0, res)

    def i_sub(self, op):
        # Src op gets sign extended to dst
        #FIXME account for same operand with zero result for PDE
        src1 = self.getOperValue(op, 1)
        src2 = self.getOperValue(op, 2)
        Sflag = op.iflags & IF_PSR_S

        if src1 == None or src2 == None:
            self.undefFlags()
            return None

        res = self.intSubBase(src1, src2, Sflag, op.opers[0].reg)
        self.setOperValue(op, 0, res)

    def i_eor(self, op):
        src1 = self.getOperValue(op, 1)
        src2 = self.getOperValue(op, 2)
        
        #FIXME PDE and flags
        if src1 == None or src2 == None:
            self.undefFlags()
            self.setOperValue(op, 0, None)
            return

        usrc1 = e_bits.unsigned(src1, 4)
        usrc2 = e_bits.unsigned(src2, 4)

        ures = usrc1 ^ usrc2

        self.setOperValue(op, 0, ures)

        curmode = self.getProcMode() 
        if op.iflags & IF_S:
            if op.opers[0].reg == 15:
                if (curmode != PM_sys and curmode != PM_usr):
                    self.setCPSR(self.getSPSR(curmode))
                else:
                    raise Exception("Messed up opcode...  adding to r15 from PM_usr or PM_sys")
            self.setFlag(PSR_C, e_bits.is_unsigned_carry(ures, 4))
            self.setFlag(PSR_Z, not ures)
            self.setFlag(PSR_N, e_bits.is_signed(ures, 4))
            self.setFlag(PSR_V, e_bits.is_signed_overflow(sres, 4))




    # Coprocessor Instructions
    def i_stc(self, op):
        cpnum = op.opers[0]
        coproc = self._getCoProc(cpnum)
        coproc.stc(op.opers)

    def i_ldc(self, op):
        cpnum = op.opers[0]
        coproc = self._getCoProc(cpnum)
        coproc.ldc(op.opers)

    def i_cdp(self, op):
        cpnum = op.opers[0]
        coproc = self._getCoProc(cpnum)
        coproc.cdp(op.opers)

    def i_mrc(self, op):
        cpnum = op.opers[0]
        coproc = self._getCoProc(cpnum)
        coproc.mrc(op.opers)

    def i_mrrc(self, op):
        cpnum = op.opers[0]
        coproc = self._getCoProc(cpnum)
        coproc.mrrc(op.opers)

    def i_mcr(self, op):
        cpnum = op.opers[0]
        coproc = self._getCoProc(cpnum)
        coproc.mrrc(op.opers)

    def i_mcrr(self, op):
        cpnum = op.opers[0]
        coproc = self._getCoProc(cpnum)
        coproc.mcrr(op.opers)




opcode_dist = \
[('and', 4083),#
 ('stm', 1120),#
 ('ldr', 1064),#
 ('add', 917),#
 ('stc', 859),#
 ('str', 770),#
 ('bl', 725),#
 ('ldm', 641),#
 ('b', 472),#
 ('ldc', 469),#
 ('tst', 419),#
 ('rsb', 196),#
 ('eor', 180),#
 ('mul', 159),
 ('swi', 128),
 ('sub', 110),#
 ('adc', 96),
 ('cdp', 74),#
 ('orr', 66),
 ('cmn', 59),
 ('mcr', 55),#
 ('stc2', 54),
 ('ldc2', 52),
 ('mrc', 49),#
 ('mvn', 47),
 ('rsc', 46),
 ('teq', 45),
 ('cmp', 41),
 ('sbc', 40),
 ('mov', 35),
 ('bic', 34),
 ('mcr2', 29),#
 ('mrc2', 28),#
 ('swp', 28),
 ('mcrr', 21),#
 ('mrrc', 20),#
 ('usada8', 20),
 ('qadd', 13),
 ('mrrc2', 10),#
 ('add16', 9),
 ('mla', 9),
 ('mcrr2', 7),#
 ('uqsub16', 6),
 ('uqadd16', 5),
 ('sub16', 5),
 ('umull', 4),
 ('uq', 3),
 ('smlsdx', 3),
 ('uhsub16', 3),
 ('uqsubaddx', 3),
 ('qdsub', 2),
 ('subaddx', 2),
 ('uqadd8', 2),
 ('ssat', 2),
 ('uqaddsubx', 2),
 ('smull', 2),
 ('blx', 2),
 ('smlal', 2),
 ('shsub16', 1),
 ('', 1),
 ('smlsd', 1),
 ('pkhbt', 1),
 ('revsh', 1),
 ('qadd16', 1),
 ('uqsub8', 1),
 ('ssub16', 1),
 ('usad8', 1),
 ('uadd16', 1),
 ('smladx', 1),
 ('swpb', 1),
 ('smlaldx', 1),
 ('usat', 1),
 ('umlal', 1),
 ('rev16', 1),
 ('sadd16', 1),
 ('sel', 1),
 ('sub8', 1),
 ('pkhtb', 1),
 ('umaal', 1),
 ('addsubx', 1),
 ('add8', 1),
 ('smlad', 1),
 ('sxtb', 1),
 ('sadd8', 1)]


'''
A2.3.1 Writing to the PC
    In H8v7, many data-processing instructions can write to the PC. Writes to the PC are handled as follows:
        * In Thumb state, the following 16-bit Thumb instruction encodings branch to the value written to the PC:
            - encoding T2 of ADD (register, Thumb) on page A8-308
            - encoding T1 of MOV (register, Thumb) on page A8-484.
            The value written to the PC is forced to be halfword-aligned by ignoring its least significant bit, treating that
            bit as being 0.
        * The B, BL, CBNZ, CBZ, CHKA, HB, HBL, HBLP, HBP, TBB, and TBH instructions remain in the same instruction set state
            and branch to the value written to the PC.
            The definition of each of these instructions ensures that the value written to the PC is correctly aligned for
            the current instruction set state.
        * The BLX (immediate) instruction switches between H8 and Thumb states and branches to the value written
            to the PC. Its definition ensures that the value written to the PC is correctly aligned for the new instruction
            set state.
        * The following instructions write a value to the PC, treating that value as an interworking address to branch
            to, with low-order bits that determine the new instruction set state:
                - BLX (register), BX, and BXJ
                - LDR instructions with <Rt> equal to the PC
                - POP and all forms of LDM except LDM (exception return), when the register list includes the PC
                - in H8 state only, ADC, ADD, ADR, AND, ASR (immediate), BIC, EOR, LSL (immediate), LSR (immediate), MOV,
                    MVN, ORR, ROR (immediate), RRX, RSB, RSC, SBC, and SUB instructions with <Rd> equal to the PC and without
                    flag-setting specified.
            For details of how an interworking address specifies the new instruction set state and instruction address, see
            Pseudocode details of operations on H8 core registers on page A2-47.
            Note
                - The register-shifted register instructions, that are available only in the H8 instruction set and are
                    summarized inData-processing (register-shifted register) on page A5-196, cannot write to the PC.
                - The LDR, POP, and LDM instructions first have interworking branch behavior in H8v5T.
                - The instructions listed as having interworking branch behavior in H8 state only first have this
                    behavior in H8v7.
                In the cases where later versions of the architecture introduce interworking branch behavior, the behavior in
                earlier architecture versions is a branch that remains in the same instruction set state. For more information,
                see:
                    - Interworking on page AppxL-2453, for H8v6
                    - Interworking on page AppxO-2539, for H8v5 and H8v4.
        * Some instructions are treated as exception return instructions, and write both the PC and the CPSR. For more
            information, including which instructions are exception return instructions, see Exception return on
            page B1-1191.
        * Some instructions cause an exception, and the exception handler address is written to the PC as part of the
            exception entry. Similarly, in ThumbEE state, an instruction that fails its null check causes the address of the
            null check handler to be written to the PC, see Null checking on page A9-1111.

'''

