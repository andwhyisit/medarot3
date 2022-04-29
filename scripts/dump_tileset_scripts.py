#!/bin/python

# Script to initially dump tileset scripts

import os, sys
from collections import OrderedDict
from functools import partial
from pathlib import Path

sys.path.append(os.path.join(os.path.dirname(__file__), 'common'))
from common import utils, tilesets, png, gfx

roms = ([
            ("baserom_kabuto.gbc", "kabuto"), 
            ("baserom_kuwagata.gbc", "kuwagata")
        ])

instruction_roots = ([
        (0x2e, 0x4000),
        (0x63, 0x4000)
    ])

raw_path = sys.argv[1]
gfx_output_path = sys.argv[2]
scripts_res_path = sys.argv[3]
gfx_src_path = sys.argv[4]
version_src_path = sys.argv[5]

output_file = os.path.join(gfx_src_path, "tileset_scripts.asm")
nametable = OrderedDict()
namefile = None
meta_tileset_script_names_file = os.path.join(scripts_res_path, "meta_tileset_script_names.tbl")

if os.path.exists(meta_tileset_script_names_file):
    nametable = utils.read_table(meta_tileset_script_names_file, keystring=True)
else:
    namefile = open(meta_tileset_script_names_file, "w")

gfx_banks = [] # Keep track of banks with graphics

def parse_and_log_bank(f):
    b = utils.read_byte(f)
    if b not in gfx_banks:
        gfx_banks.append(b)
    return b

commands = {}

class TilesetCommand():
    def __init__(self, name, bts = 1, parser=None, is_end = False):
        self.name = name
        self.bts = bts
        if not parser:
            parser = { 0: lambda x: None, 1: utils.read_byte, 2: utils.read_short }[self.bts]
        self.parser = parser
        self.is_end = is_end

commands[0xFB] = TilesetCommand("TilesetSetVRAMBank") # FB XX, set active VRAM bank
commands[0xFC] = TilesetCommand("TilesetRunPreset") # FC XX, loads preset command from table
commands[0xFD] = TilesetCommand("TilesetSetGraphicsBank", parser = parse_and_log_bank) # FD XX, set source bank to load tiles from
commands[0xFE] = TilesetCommand("TilesetSetVRAMIndex") # FE XX, set destination index in VRAM to draw to
commands[0xFF] = TilesetCommand("TilesetEnd", bts = 0, is_end = True) # FF, end script
commands[None] = TilesetCommand("TilesetRender", bts = 2, parser = utils.read_byte) # XX YY, No command specified, render XX tiles from index YY in the source graphics table

try:
    version = roms[1]
    version_suffix = version[1]
    with open(output_file, 'w') as output:
        output.write(f"; Autogenerated by {sys.argv[0]}\n\n")
        for symbol in commands:
            command = commands[symbol]
            output.write(f"{command.name}: MACRO\n")
            if symbol:
                output.write(f"  db ${symbol:02X}\n")
            for i in range(command.bts):
                output.write(f"  db \\{i + 1}\n")
            output.write("  ENDM\n\n")

        with open(version[0], "rb") as rom:
            for root_idx, root in enumerate(instruction_roots):
                addr = utils.rom2realaddr(root)
                # Seek to start of pointer table
                rom.seek(addr)
                # Assume the first address we read also indicates the end of the pointer table
                pointers = [(addr, utils.read_short(rom))]
                end_addr = utils.rom2realaddr((root[0], pointers[0][1]))
                # Determine number of entries in list
                count = ((end_addr - addr) // 2)
                pointers += [(rom.tell(), utils.read_short(rom)) for i in range(0, count - 1)]

                output.write(f'SECTION "Tileset Script Table {root_idx}", ROMX[${root[1]:04X}], BANK[${root[0]:02X}]\n')
                output.write(f'TilesetScripts{root_idx}::\n')
                
                scripts = OrderedDict()
                addr_id_map = OrderedDict()
                for ptr_idx, ptr in enumerate(pointers):
                    addr = ptr[1]
                    if addr in addr_id_map:
                        ptr_id = addr_id_map[addr]
                    else:
                        ptr_id = f"{root_idx:02X}_{ptr_idx:04X}"
                        if namefile:
                            nametable[ptr_id] = f"TilesetScript{ptr_id}"
                            namefile.write(f"{ptr_id}={nametable[ptr_id]}\n")
                        
                        addr_id_map[addr] = ptr_id

                        # Read script if it's an new one
                        rom.seek(utils.rom2realaddr((root[0], addr)))
                        scripts[ptr_id] = [f"{nametable[ptr_id]}::"]
                        while True:
                            b = utils.read_byte(rom)
                            cmd = commands.get(b, commands[None])
                            params = cmd.parser(rom)
                            
                            if params is not list:
                                params = [params]
                                if b not in commands:
                                    params = [b] + params

                            params = [f"${i:02X}" for i in params if i is not None]

                            scripts[ptr_id].append(f"  {cmd.name} {','.join(params)}")

                            if cmd.is_end:
                                break

                    output.write(f"  dw {nametable[ptr_id]}\n")
                output.write('\n')

                for ptr_id in scripts:
                    for line in scripts[ptr_id]:
                        output.write(f"{line}\n")
                    output.write("\n")
finally:
    if namefile:
        namefile.close()

def dump_2bpp_to_png(filename, data):
    with open(filename, "wb") as uncompressed:
        width, height, palette, greyscale, bitdepth, px_map = gfx.convert_2bpp_to_png(data)
        w = png.Writer(
            width,
            height,
            palette=palette,
            compression=9,
            greyscale=greyscale,
            bitdepth=bitdepth
        )
        w.write(uncompressed, px_map)

# Dump tilesets used by the scripts
output_file = os.path.join(version_src_path, "partial_tilesets_table.asm")

with open(output_file, 'w') as output:
    output.write(f"; Autogenerated by {sys.argv[0]}\n\n")


    name_data_map = OrderedDict()
    pointer_ids = {}

    for version_idx, version in enumerate(roms):
        version_suffix = version[1]

        with open(version[0], "rb") as rom: 
            for bank_idx, bank in enumerate(gfx_banks):
                # all banks have graphics tables start at 0x4000
                addr = utils.rom2realaddr((bank, 0x4000))

                # Seek to start of pointer table
                rom.seek(addr)

                # Assume the first address we read also indicates the end of the pointer table
                pointers = [(addr, utils.read_short(rom))]
                end_addr = utils.rom2realaddr((bank, pointers[0][1]))

                # Determine number of entries in list
                count = ((end_addr - addr) // 2)
                pointers += [(rom.tell(), utils.read_short(rom)) for i in range(0, count - 1)]

                # The last key should be considered the terminator, there's no tileset here
                terminator = pointers[-1][1]
                addr_id_map = OrderedDict()
                addr_id_map[terminator] = f"PartialTilesetTerminator{bank_idx}"

                for ptr_idx, ptr in enumerate(pointers):
                    addr = ptr[1]
                    if addr in addr_id_map:
                        ptr_id = addr_id_map[addr]
                    else:
                        ptr_id = f"PartialTileset{bank_idx:02X}{ptr_idx:02X}"
                        addr_id_map[addr] = ptr_id

                    # Both versions have the same number of pointers, so we can cheat here
                    if version_idx == 0:
                        if bank_idx not in pointer_ids:
                            pointer_ids[bank_idx] = [ptr_id]
                        else:
                            pointer_ids[bank_idx].append(ptr_id)

                # Get the sizes by doing some subtraction on the known addresses
                sizes = {}
                addresses = sorted(addr_id_map)
                for idx, addr in enumerate(addresses):
                    if addr == terminator:
                        break
                    # Terminator should be 'highest' address
                    sizes[addr] = addresses[idx + 1] - addr

                for idx, addr in enumerate(addr_id_map):
                    if addr == terminator:
                        continue
                    real_addr = utils.rom2realaddr((bank, addr))
                    size = sizes[addr]
                    rom.seek(real_addr)
                    tileset_data = rom.read(size)

                    if bank_idx not in name_data_map:
                        name_data_map[bank_idx] = {}

                    if addr_id_map[addr] in name_data_map[bank_idx] and tileset_data != name_data_map[bank_idx][addr_id_map[addr]]:
                        if not isinstance(name_data_map[bank_idx][addr_id_map[addr]], list):
                            name_data_map[bank_idx][addr_id_map[addr]] = [name_data_map[bank_idx][addr_id_map[addr]]]
                        name_data_map[bank_idx][addr_id_map[addr]].append(tileset_data)
                    elif addr_id_map[addr] not in name_data_map[bank_idx]:
                        name_data_map[bank_idx][addr_id_map[addr]] = tileset_data

    # Now we can actually generate the files
    version_files = [open(os.path.join(version_src_path, version_info[1], "partial_tilesets_table.asm"), 'w') for version_info in roms]

    try:
        for bank_idx, bank in enumerate(gfx_banks):
            output.write(f'SECTION "Partial Tilesets Table {bank_idx}", ROMX[$4000], BANK[${bank:02X}]\n')
            output.write(f'PartialTilesets{bank_idx}::\n')
            for ptr_id in pointer_ids[bank_idx]:
                output.write(f"  dw {ptr_id}\n")
            output.write("\n")

            for name in name_data_map[bank_idx]:
                data = name_data_map[bank_idx][name]

                output.write(f"{name}::\n")
                
                if not isinstance(name_data_map[bank_idx][name], list):
                    dump_2bpp_to_png(os.path.join(raw_path, f"{name}.png"), data)
                    output.write(f'  INCBIN "{os.path.join(gfx_output_path, name)}.2bpp"\n')
                else:
                    output.write(f'  INCBIN c{name}_GAMEVERSION\n')
                    for i, f in enumerate(version_files):
                        fname = f"{name}_{roms[i][1]}" 
                        f.write(f'c{name}_GAMEVERSION        EQUS "\\"{os.path.join(gfx_output_path, fname)}.2bpp\\""\n')
                        dump_2bpp_to_png(os.path.join(raw_path, f"{fname}.png"), data[i])
            
            # Last pointer is always the terminator, so just use that
            output.write(f"{pointer_ids[bank_idx][-1]}::\n\n")

    finally:
        [f.write(f'INCLUDE "{os.path.join(version_src_path, "partial_tilesets_table.asm")}"') and f.close() for f in version_files]