# FPGA design guidance

Apply these guidelines when creating or modifying FPGA designs, including RTL
generated from Python or PipelineC.

## Performance planning

- Optimize and debug incrementally. Organize the design into appropriate
  hierarchical blocks and partitions so major blocks can be evaluated separately.
- Register all block inputs and outputs, accounting for the resulting latency in
  interfaces and integration.
- When compiling major blocks individually, target a higher speed than the final
  design requires. Retain approximately 10–20% timing margin at the block level to
  help achieve timing closure after integration.
- Plan around the resource types and locations available in the target device
  while coding the design, including RAM blocks, DSP blocks, PLLs or equivalent
  clocking resources, and transceivers where available.
- Pipeline the design to improve performance, keeping data and control signals
  aligned through the added stages.

## Synchronous design practices

- Follow synchronous design practices to simplify timing constraints and improve
  reliability across process, voltage, and temperature (PVT) conditions.
- Use clocked state transitions. Avoid asynchronous logic that depends on
  propagation delays or clock skew for correct operation; those assumptions do
  not scale reliably across device families, architectures, or speed grades.
- Account for glitches and race conditions when interfacing with asynchronous
  signals, and synchronize crossings appropriately.
- Provide appropriate timing constraints so synthesis and place-and-route tools
  can optimize the design and produce meaningful timing analysis. Synchronous
  structure alone does not guarantee timing closure; check timing after fitting
  or place-and-route and after integrating blocks.

These guidelines are adapted from the supplied Intel Quartus Prime Pro Edition
guidance, sections 1.5.1, “Performance Planning General Guidelines,” and 1.5.2,
“Follow Synchronous Design Practices.” For further background, see “Synchronous
FPGA Design Practices” in the Intel Quartus Prime Pro Edition User Guide: Design
Recommendations. Apply the principles using this project's target device and
toolchain.
