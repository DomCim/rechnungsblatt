import sys
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import Color, CMYKColor
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from PIL import Image, ImageDraw

MODE = sys.argv[1]          # "gut" = Schriften eingebettet, "boese" = Base-14
OUT  = sys.argv[2]
W, H = A4

if MODE == "gut":
    pdfmetrics.registerFont(TTFont("LB", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"))
    pdfmetrics.registerFont(TTFont("LR", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"))
    FB, FR = "LB", "LR"
else:
    FB, FR = "Helvetica-Bold", "Helvetica"   # Base-14, NICHT eingebettet

img = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.ellipse((20, 20, 380, 380), fill=(200, 30, 40, 255))
d.ellipse((110, 110, 290, 290), fill=(255, 255, 255, 0))
img.save("logo.png")

c = canvas.Canvas(OUT, pagesize=A4)
c.setProducer("Adobe InDesign 19.0 (Macintosh)")
c.setFillColor(CMYKColor(0.85, 0.20, 0.0, 0.10))          # CMYK
c.rect(0, H-45*mm, W, 45*mm, stroke=0, fill=1)
c.saveState()
c.setFillColor(Color(1,1,1, alpha=0.35))                   # Transparenz
c.rect(0, H-50*mm, W, 6*mm, stroke=0, fill=1)
c.restoreState()
c.drawImage("logo.png", 150*mm, H-40*mm, 32*mm, 32*mm, mask="auto")  # Alpha-Bild
c.setFillColorRGB(1,1,1)
c.setFont(FB, 20); c.drawString(20*mm, H-28*mm, "Muster & Partner GmbH")
c.setFont(FR, 9);  c.drawString(20*mm, H-35*mm, "Handwerk seit 1978")
c.setFillColor(CMYKColor(0.85,0.20,0.0,0.10)); c.rect(0,0,W,22*mm,stroke=0,fill=1)
c.setFillColorRGB(1,1,1); c.setFont(FR, 7.5)
for i, line in enumerate([
    "Muster & Partner GmbH · Bahnhofstr. 12 · 95119 Naila",
    "Tel 09282 12345 · info@muster-partner.de · USt-IdNr. DE123456789",
    "Sparkasse Hochfranken · IBAN DE02 7805 0000 0001 2345 67",
]):
    c.drawString(20*mm, 15*mm - i*3.5*mm, line)
c.showPage(); c.save()
print("erzeugt:", OUT, MODE)
