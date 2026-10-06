Unmodified backend from https://github.com/DFiantWorks/vga-monitor-sim
revision 4fb79a2f32ef1eb5572903eb7494105716e85c14, MIT licensed.

fpgatool calls the C API directly, forwarding changes to the simulated board
pins with simulation timestamps. RGB444 channels expand to RGB888 by *17.
