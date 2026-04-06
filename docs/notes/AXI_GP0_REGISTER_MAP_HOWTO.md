# CPU ↔ PL over AXI GP0 (register map)

Informal notes on how we wire this in `rp_ads1278`, in case you want to **reproduce the same setup** on another Zynq-7000 Red Pitaya (or similar) build: the **ARM (PS)** talks to the **PL** over **AXI4-Lite** on **GP0 (`M_AXI_GP0`)**. From Linux it looks like a **memory-mapped register block** — not FPGA DMA into DDR.

---

## 1. Mental model

| Layer | Role |
|--------|------|
| **PS (CPU)** | AXI **master**: issues reads/writes to a fixed physical address range. |
| **PL** | AXI4-Lite **slave**: decodes addresses into **registers**; logic updates them; the CPU reads them back. |

**Important:** This is **not** “FPGA writes into the same DDR buffer the CPU uses” unless you add a separate **AXI master** (e.g. HP port + writer). Here, **sharing** means: **MMIO registers** the CPU accesses with loads/stores (or `mmap`).

Naming note: In Xilinx block diagrams the PS exports **`M_AXI_GP0`** — “M” means this interface is mastered **by the PS** toward the PL. Top-level RTL ties that bundle to the **slave** in fabric.

---

## 2. Vivado block design (PS + GP0 + address map)

### 2.1 Enable the GP master and export it

In the Processing System 7 (PS7) configuration, enable **AXI GP0** as a master to the PL. The generated block design in this repo exposes a **top-level interface port** `M_AXI_GP0` and, for Red Pitaya-style designs, often inserts an **AXI Protocol Converter** so the PS’s full AXI4 is converted to **AXI4-Lite** for simple slaves.

Relevant excerpts from `fpga/source/system_design_bd_rp125_14/system.tcl`:

- **Port** (master from PS, toward PL): `M_AXI_GP0` with `CONFIG.PROTOCOL {AXI4LITE}`.
- **Clock association:** `PL_ACLK` is associated with `M_AXI_GP0` so Vivado knows the bus timing domain.
- **Address assignment:** the PL slave is given a **fixed region** in the PS memory map.

Example from the same TCL (values are project-specific; treat `0x40000000` / `4 KiB` as the **contract** between HW and SW):

```tcl
# Slave segment visible to the PS "Data" address space:
assign_bd_address -offset 0x40000000 -range 0x00001000 \
  -target_address_space [get_bd_addr_spaces processing_system7/Data] \
  [get_bd_addr_segs M_AXI_GP0/Reg] -force
```

**Worth double-checking:**

- **`offset`** (physical base) and **`range`** (size) — software should match unless you’ve remapped in the device tree.
- **`PL_ACLK`** matches what you constrained in XDC and what the slave RTL actually sees.

### 2.2 Optional but common: `axi_protocol_converter`

Connections in this project follow: `processing_system7/M_AXI_GP0` → **converter** → **top port** `M_AXI_GP0`. The top-level slave then hooks to that exported port (via the PS wrapper — see §3).

### 2.3 IRQ from PL to PS (optional)

If you want Linux interrupts from the PL, export a **single interrupt line** into the PS. This repo uses a port `IRQ` wired to `processing_system7/IRQ_F2P` and enables `PCW_IRQ_F2P_INTR`. The slave can pulse or level-drive `irq`; whatever handles it in software needs to **clear the condition** in PL or mask it, or the ISR will fire forever.

---

## 3. RTL structure in this repository

Three pieces work together: **interface** → **PS wrapper** → **AXI slave + user logic**.

### 3.1 `axi4_lite_if` — SystemVerilog interface bundle

File: `fpga/rtl/axi4_lite_if.sv`

This defines all AXI4-Lite channels (`AW`, `W`, `B`, `AR`, `R`) plus **`modport m`** (master) and **`modport s`** (slave). Using an interface keeps the top-level wiring readable.

**Master modport** (what the PS side drives toward the PL):

```systemverilog
modport m (
  input  ACLK, ARESETn,
  output AWADDR, AWPROT, AWVALID, input AWREADY,
  output WDATA, WSTRB, WVALID, input WREADY,
  input  BRESP, BVALID, output BREADY,
  output ARADDR, ARPROT, ARVALID, input ARREADY,
  input  RDATA, RRESP, RVALID, output RREADY
);
```

**Slave modport** (what the register block implements):

```systemverilog
modport s (
  input  ACLK, ARESETn,
  input  AWADDR, AWPROT, AWVALID, output AWREADY,
  input  WDATA, WSTRB, WVALID, output WREADY,
  output BRESP, BVALID, input BREADY,
  input  ARADDR, ARPROT, ARVALID, output ARREADY,
  output RDATA, RRESP, RVALID, input RREADY
);
```

### 3.2 `red_pitaya_ps` — instantiate Vivado `system`, connect GP0

File: `fpga/rtl/red_pitaya_ps.sv`

The wrapper instantiates the **Vivado-generated** `system` module and **maps `M_AXI_GP0_*` ports to the `axi4_lite_if` master modport** (`axi4_lite_if.m`). The PS also supplies **`PL_ACLK`** and **`PL_ARESETn`** that must match the clock you use for the bus and slave.

```systemverilog
system system (
  ...
  .PL_ACLK            (bus.ACLK   ),
  .PL_ARESETn         (bus.ARESETn),
  .M_AXI_GP0_araddr   (bus.ARADDR ),
  ...
  .M_AXI_GP0_wvalid   (bus.WVALID ),
  .IRQ                (irq)       // PL → PS interrupt input
);
```

### 3.3 Top-level — one shared bus, slave + PS

File: `fpga/rtl/red_pitaya_top.sv`

The top creates **one** `axi4_lite_if` instance and connects:

- **`red_pitaya_ps`** → master side of `bus`
- **`ads1278_axi_slave`** → slave side of `bus`

```systemverilog
axi4_lite_if bus (.ACLK (adc_clk), .ARESETn (adc_rstn));

red_pitaya_ps ps (
  ...
  .bus (bus)
);

ads1278_axi_slave u_ads1278 (
  ...
  .bus (bus)
);
```

**Clock/reset:** `ACLK` and `ARESETn` should be the **same** nets the slave uses for `always_ff @(posedge bus.ACLK)`. Crossing clock domains on this bus without a synchronizer or CDC block is asking for pain.

### 3.4 `ads1278_axi_slave` — full AXI4-Lite slave + register decode

File: `fpga/rtl/ads1278_axi_slave.sv`

It’s a decent **reference** for:

- Latching **write address** / **read address**
- Asserting **`AWREADY`/`WREADY`/`ARREADY`** per transfer
- Generating **`BVALID`** / **`RVALID`** handshakes
- **Write strobes** (`WSTRB`) for byte-wise writes
- **Read mux** from internal registers and datapath (`RDATA`)

The header documents the **register map** (offsets relative to the AXI base, e.g. `0x40000000`):

| Offset | Name | Access |
|--------|------|--------|
| `0x00` … `0x1C` | CH1 … CH8 | R |
| `0x20` | STATUS | R |
| `0x24` | CTRL | R/W |
| `0x28` | EXTCLK_DIV | R/W |

**Minimal read mux pattern** (simplified; see the file for the full state machine):

```systemverilog
always_ff @(posedge bus.ACLK)
if (slv_reg_rden) begin
  case (axi_araddr)
    4'h0: bus.RDATA <= ch_data[0];
    // ...
    default: bus.RDATA <= 32'hDEAD_BEEF;
  endcase
end
```

**Minimal write pattern** (byte enables):

```systemverilog
if (slv_reg_wren) begin
  case (axi_awaddr)
    4'h9: begin
      for (int unsigned i = 0; i < 4; i++)
        if (bus.WSTRB[i])
          ctrl_reg[(i*8)+:8] <= bus.WDATA[(i*8)+:8];
    end
    default: ;
  endcase
end
```

If you’re sketching something minimal before folding in acquisition logic, a stub with e.g. **`REG_ID`** @ `0x00` (read-only `0x12345678`) and **`REG_LED`** @ `0x04` (R/W) is enough to shake out the bus end-to-end with §4, then grow from there.

---

## 4. Software on Linux (mmap the register block)

### 4.1 Physical base address

Per the address map in §2.1, this project’s GP0 segment is at **`0x40000000`** with **`0x1000`** bytes — **confirm** in Vivado’s *Address Editor* on your build; don’t assume it if you’ve changed the BD.

### 4.2 Example: map and access 32-bit registers

Below is **illustrative** C code. You need **root** or a **UIO driver**; raw `/dev/mem` is common for bring-up but has security implications.

```c
#include <stdint.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <unistd.h>

#define GP0_BASE   0x40000000u
#define GP0_SIZE   0x1000u

#define OFF_CH1    0x00u
#define OFF_CTRL   0x24u

int main(void) {
    int fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (fd < 0) return 1;

    volatile uint32_t *regs = mmap(NULL, GP0_SIZE,
        PROT_READ | PROT_WRITE, MAP_SHARED, fd, GP0_BASE);
    if (regs == MAP_FAILED) { close(fd); return 1; }

    uint32_t ch1 = regs[OFF_CH1 / 4];

    uint32_t ctrl = regs[OFF_CTRL / 4];
    ctrl |= (1u << 1);              // example: set enable bit
    regs[OFF_CTRL / 4] = ctrl;

    (void)ch1;
    munmap((void *)regs, GP0_SIZE);
    close(fd);
    return 0;
}
```

**Endianness:** AXI and ARM are typically **little-endian** for 32-bit words; `uint32_t` array indexing matches word-aligned offsets.

### 4.3 Caching

MMIO must be **uncached**. `mmap` of device memory is typically set up uncached by the kernel mapping; if you use a **pointer to a normal RAM address** by mistake, you will see stale values. For bare-metal, configure the page tables accordingly.

---

## 5. Bring-up and debug

1. **Reads first:** A read-only ID register is the fastest way to confirm the CPU (or an AXI testbench) sees what you think.
2. **ILA:** `AWVALID/AWREADY`, `WVALID`, `ARVALID`, plus a few register bits, usually tell the story in hardware.
3. **Garbage reads:** Compare **Address Editor** base with **RTL offsets** (watch word vs byte — slaves often use `AW` and `ADDR_LSB` to strip byte address bits).
4. **Reset:** Don’t release `ARESETn` until `ACLK` is clean and stable.

---

## 6. Where things live in this repo

| Topic | File |
|--------|------|
| AXI4-Lite signal bundle | `fpga/rtl/axi4_lite_if.sv` |
| PS7 + `M_AXI_GP0` wiring | `fpga/rtl/red_pitaya_ps.sv` |
| Top-level hookup | `fpga/rtl/red_pitaya_top.sv` |
| Slave + register map | `fpga/rtl/ads1278_axi_slave.sv` |
| Block design + address | `fpga/source/system_design_bd_rp125_14/system.tcl` |

---

## 7. What this guide does *not* cover

- **AXI HP (high-performance) ports** and FPGA masters writing **DDR** — different IP and constraints (`PCW_USE_S_AXI_HP0`, etc.). This project keeps HP disabled in TCL.
- **Full Linux kernel drivers** — production systems often use **UIO** or a **platform driver** instead of `/dev/mem`.

That’s the same **GP0 + AXI4-Lite slave + mmap** path this project uses for ADS1278 control and status.
