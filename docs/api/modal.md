# Modal Analysis Module

Modal analysis tools for mode fitting and modal parameter extraction.
A fit is stored as a `ModalData` (see [Data Structures](datastructure.md)),
whose matrix `M` has one row per mode: the natural frequency `fn` and
damping ratio `zn`, then the modal-constant amplitude `an`, phase `pn`
and residual terms `rk`, `rm` for each channel.

## Fitting

::: pydvma.modal.modal_fit_single_channel

::: pydvma.modal.modal_fit_all_channels

::: pydvma.modal.modal_refine

## Reconstruction

::: pydvma.modal.reconstruct_transfer_function

::: pydvma.modal.reconstruct_transfer_function_global

::: pydvma.modal.estimate_global_constants

## Helpers

::: pydvma.modal.unpack_matrix
