============
PDF Decanter
============

This is a simple program optimized for PDF-based presentations.  I
mostly use it in conjunction with LaTeX-beamer_, but actually the
source of the PDF is arbitrary (e.g. one may export slides as PDF from
impress or the like, too).

I wrote this mainly for the following reasons:

1. I am using the ``\pause``-feature of LaTeX-beamer_, which lets
   stuff appear one-by-one.  This works by generating multiple PDF pages
   per slide, i.e. each content frame is sub-divided into multiple
   animation frames.  Common PDF readers will display ridiculous page
   numbers like "35 of 245" for a 20 minute presentation; I wanted
   PDF Decanter to recognize multiple PDF pages that belong together and
   be able to **present an overview of the logical slides**, with
   animation frames batched together.

2. Although I like some(!) animated transitions, I find it highly
   irritating to see the logo of one PDF page leave the screen to the
   left, only to have it appear (on the next page) from the right again.
   PDF Decanter shall recognize and **not animate content that does not
   change**.

3. Although possible, it is a real hassle to embed videos in PDF
   files.  (And presentation then only works with – *yuck* – Adobe
   Acrobat Reader on Windows or OS X, while I normally use Linux.)  I
   figured that if I wrote my own software, I could make it as easy as
   possible to **embed videos or other (dynamic) custom content**.

I have much more in mind than what is already implemented, but the
current version should already work well for many presentations.

Other interesting features:

* Overview mode displays already seen slides differently from unseen
  slides.

* In the presence of a PDF outline (e.g. using sectioning with
  LaTeX-beamer), the overview will separate sections visually.

* Hyperlinks within the presentation are supported.

The name "PDF Decanter" stands for "PDF decomposer for animated
transitions whose expedience rocks".  (I am not too happy with the
last part, but otherwise it more or less conveys the gist of the
software.  If you have a better suggestion, please tell me.)  ;-)

Usage
=====

Start PDF Decanter like this::

  <path_to_pdfdecanter>/pdf_decanter.py mypresentation.pdf

This will render the PDF into images (requiring the ``pdftoppm``_
commandline program that usually comes with the ``poppler-utils``
package) and start the presentation.  The rendering process takes a
while, so the result will be cached.

The following keys are available in **presentation mode** (fullscreen slide view):

======================== ==============
Space, Right, PgDown     Next slide
Backspace, Left, PgUp    Previous slide
Home                     First Slide
Tab                      Show overview
======================== ==============

The following keybindings are **always** available (i.e. in both modes):

============== ===================================================
0-9 + Enter    go to slide number #
F, L           jump to [F]irst / [L]ast frame state of current slide
Shift-F        Enter/leave [F]ullscreen mode
Shift-Q        [Q]uit
(Shift-P       Debugging: Toggle navigation visibility)
============== ===================================================

In the **overview mode**, these are the keybindings:

================= =================================================
Enter, Tab        Back to presentation mode
Cursor keys       Move yellow slide cursor
Home              First Slide
Shift-U           [U]ncover all slides
Shift-R           [R]eset all slides to covered state (and go home)
================= =================================================

Bugs and Limitations
====================

I am aware of a lot of bugs and limitations, and I will try to make
this more transparent by filing `issues at GitHub
<https://github.com/hmeine/pdfdecanter/issues>`_.  I tried to get to
a working state and publish this as soon as possible, which means that
right now:

* Presentations with non-white background may not work as well.

* The header transition is buggy (if one looks closely).

* Overall, the current model of a frame as "previous frame + overlaid
  patches" does not lend to an optimal transition implementation.  It
  would be better to

  * have an explicit representation of all stuff that appears on one
    page and to

  * base each transition on computed differences between frames.

* The cache location is system-wide; it should be per-user for
  security reasons! (unpickling is dangerous.)  I added a warning to
  make this more obvious; don't use the current code on a shared,
  untrusted computer!

Unfinished / planned features:

* Opacity animations should be recognized (leading to smaller file
  sizes and potentially better transition animations).

* Elements overlapping header/footer should be supported and not lead
  to new slides.

* Such elements could get a different transition than fade-in
  (e.g. zoom-in or the like).

* Frame repeations after many pages (e.g. repeated outline slides)
  should also be recognized.  (Again, this could lead to smaller files
  and better transitions between these slides.)

* Zooming (e.g. to the original / increased resolution of embedded
  figures)

* The slide numbers should (optionally) be displayed somewhere in
  order to make the "jump to slide" feature more useful.

.. _LaTeX-beamer: https://bitbucket.org/rivanvx/beamer/overview
.. _pdftoppm: http://poppler.freedesktop.org/
