# Round 7 feedback — 2026-07-09 (first lab-testing round after v2.0.0)

Raw feedback from Tore, verbatim in intent, lightly reformatted.
Triage/disposition added below each item as work proceeds.

## 1. Floating axis-control box placement
> The axis control floating box does look a bit awkward covering part of
> the top right of the plot all the time. Is there a natural alternative?

Disposition: TBD (design question — propose alternative).

## 2. Sono axis controls broken + messy bar
> Sono axis controls seem to be x and y go from 0 to 1 and don't do
> anything. And the whole bar there with 'y log lin / colour dB lin' is
> just a bit messy.

Disposition: BUG (regression/gap from d02dd00) + UI cleanup.

## 3. Fit damping UI — no interactive plot
> Fit damping brings up a weirdly placed box of fn and zn, but no
> interactive plot with peak threshold control or line for choosing
> where (in time) to find those peaks. I provided a prototype in the
> prev code, there should still be a screenshot for the kind of fit
> line, and the methods should all still exist.

Disposition: FEATURE REBUILD (Qt prototype at qt-final; screenshot in
dev/screenshots/).

## 4. Fit damping modes: by peaks / by band
> Include a fit damping toggle (by peaks, and by band). Peaks: find
> peaks, fit according to the decay line, accurate freq estimation from
> the phase. By band: apply a series of Band Pass filters to extract
> bands (options: all, oct, third-oct, 10th-dec), then use the Schroeder
> decay integral and fit method to estimate band-centred Q factors, or
> band acoustic decay metrics (ET, T20/30, RT60) etc.

Disposition: NEW FEATURE (medium-large; needs design).

## 5. CWT resolution control + does fit use CWT?
> Does CWT provide more refined control of its freq resolution (via its
> Q factor of the wavelets? or...?) And does fit damping pick up the CWT
> data if available rather than the STFT, or always use STFT?

Disposition: QUESTION → answer; possibly small enhancement.

## 6. Fit lines local vs global
> In Fit mode, clicking a fit shows a bold fit line for one chan and
> global fit lines for all, but no local fit line selection options. I'd
> want all local lines for all sets/chans, and also global. Maybe
> local/global should be a toggle choice (reflected in legend and
> lines), not an option for both?

Disposition: TBD (design lean: toggle).

## 7. Do TF/PSD see cleaned impulse data?
> Does the TF and PSD calcs pick up the cleaned impulse data, i.e. do
> they see the change, or do they always use the raw?

Disposition: QUESTION → answer definitively; fix if they use raw.

## 8. Legend with many lines
> Legends with many lines: maybe fitted lines should be in a second
> column?

Disposition: UI improvement.

## 9. Legend compact view
> Option for a compact view so it condenses to a selectable grid of dots
> with sensible arrangement and colour coding?

Disposition: UI feature.
