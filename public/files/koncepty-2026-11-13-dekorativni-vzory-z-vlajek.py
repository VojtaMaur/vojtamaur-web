"""Teselace vlajek. Python 3.10+ s Tkinterem.

    python -m pip install Pillow resvg-py
    python koncepty-2026-11-13-dekorativni-vzory-z-vlajek.py

Při prvním spuštění se stáhne archiv SVG z https://flagpedia.net/download/vector.
Soubor vlajky.zip vedle skriptu pak umožňuje práci offline.
"""

import io
import math
import queue
import threading
import tkinter as tk
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from functools import lru_cache
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import resvg_py
from PIL import Image, ImageOps, ImageTk


SVG = "http://www.w3.org/2000/svg"
XLINK = "http://www.w3.org/1999/xlink"
ET.register_namespace("", SVG)
ET.register_namespace("xlink", XLINK)
ARCHIVE = Path(__file__).resolve().with_name("vlajky.zip")
FLAG_URL = "https://flagcdn.com/svg.zip"

# České názvy katalogu. Kódy odpovídají názvům souborů v archivu Flagpedia.
COUNTRIES = dict(line.split("|", 1) for line in """ad|Andorra
ae|Spojené arabské emiráty
af|Afghánistán
ag|Antigua a Barbuda
ai|Anguilla
al|Albánie
am|Arménie
ao|Angola
aq|Antarktida
ar|Argentina
as|Americká Samoa
at|Rakousko
au|Austrálie
aw|Aruba
ax|Ålandy
az|Ázerbájdžán
ba|Bosna a Hercegovina
bb|Barbados
bd|Bangladéš
be|Belgie
bf|Burkina Faso
bg|Bulharsko
bh|Bahrajn
bi|Burundi
bj|Benin
bl|Svatý Bartoloměj
bm|Bermudy
bn|Brunej
bo|Bolívie
bq|Karibské Nizozemsko
br|Brazílie
bs|Bahamy
bt|Bhútán
bv|Bouvetův ostrov
bw|Botswana
by|Bělorusko
bz|Belize
ca|Kanada
cc|Kokosové ostrovy
cd|Kongo – Kinshasa
cf|Středoafrická republika
cg|Kongo – Brazzaville
ch|Švýcarsko
ci|Pobřeží slonoviny
ck|Cookovy ostrovy
cl|Chile
cm|Kamerun
cn|Čína
co|Kolumbie
cr|Kostarika
cu|Kuba
cv|Kapverdy
cw|Curaçao
cx|Vánoční ostrov
cy|Kypr
cz|Česko
de|Německo
dj|Džibutsko
dk|Dánsko
dm|Dominika
do|Dominikánská republika
dz|Alžírsko
ec|Ekvádor
ee|Estonsko
eg|Egypt
eh|Západní Sahara
er|Eritrea
es|Španělsko
et|Etiopie
fi|Finsko
fj|Fidži
fk|Falklandské ostrovy
fm|Mikronésie
fo|Faerské ostrovy
fr|Francie
ga|Gabon
gb-eng|Anglie
gb-nir|Severní Irsko
gb-sct|Skotsko
gb-wls|Wales
gb|Spojené království
gd|Grenada
ge|Gruzie
gf|Francouzská Guyana
gg|Guernsey
gh|Ghana
gi|Gibraltar
gl|Grónsko
gm|Gambie
gn|Guinea
gp|Guadeloupe
gq|Rovníková Guinea
gr|Řecko
gs|Jižní Georgie a Jižní Sandwichovy ostrovy
gt|Guatemala
gu|Guam
gw|Guinea-Bissau
gy|Guyana
hk|Hongkong – ZAO Číny
hm|Heardův ostrov a McDonaldovy ostrovy
hn|Honduras
hr|Chorvatsko
ht|Haiti
hu|Maďarsko
id|Indonésie
ie|Irsko
il|Izrael
im|Ostrov Man
in|Indie
io|Britské indickooceánské území
iq|Irák
ir|Írán
is|Island
it|Itálie
je|Jersey
jm|Jamajka
jo|Jordánsko
jp|Japonsko
ke|Keňa
kg|Kyrgyzstán
kh|Kambodža
ki|Kiribati
km|Komory
kn|Svatý Kryštof a Nevis
kp|Severní Korea
kr|Jižní Korea
kw|Kuvajt
ky|Kajmanské ostrovy
kz|Kazachstán
la|Laos
lb|Libanon
lc|Svatá Lucie
li|Lichtenštejnsko
lk|Srí Lanka
lr|Libérie
ls|Lesotho
lt|Litva
lu|Lucembursko
lv|Lotyšsko
ly|Libye
ma|Maroko
mc|Monako
md|Moldavsko
me|Černá Hora
mf|Svatý Martin (Francie)
mg|Madagaskar
mh|Marshallovy ostrovy
mk|Severní Makedonie
ml|Mali
mm|Myanmar (Barma)
mn|Mongolsko
mo|Macao – ZAO Číny
mp|Severní Mariany
mq|Martinik
mr|Mauritánie
ms|Montserrat
mt|Malta
mu|Mauricius
mv|Maledivy
mw|Malawi
mx|Mexiko
my|Malajsie
mz|Mosambik
na|Namibie
nc|Nová Kaledonie
ne|Niger
nf|Norfolk
ng|Nigérie
ni|Nikaragua
nl|Nizozemsko
no|Norsko
np|Nepál
nr|Nauru
nu|Niue
nz|Nový Zéland
om|Omán
pa|Panama
pe|Peru
pf|Francouzská Polynésie
pg|Papua-Nová Guinea
ph|Filipíny
pk|Pákistán
pl|Polsko
pm|Saint-Pierre a Miquelon
pn|Pitcairnovy ostrovy
pr|Portoriko
ps|Palestinská území
pt|Portugalsko
pw|Palau
py|Paraguay
qa|Katar
re|Réunion
ro|Rumunsko
rs|Srbsko
ru|Rusko
rw|Rwanda
sa|Saúdská Arábie
sb|Šalamounovy ostrovy
sc|Seychely
sd|Súdán
se|Švédsko
sg|Singapur
sh|Svatá Helena
si|Slovinsko
sj|Špicberky a Jan Mayen
sk|Slovensko
sl|Sierra Leone
sm|San Marino
sn|Senegal
so|Somálsko
sr|Surinam
ss|Jižní Súdán
st|Svatý Tomáš a Princův ostrov
sv|Salvador
sx|Svatý Martin (Nizozemsko)
sy|Sýrie
sz|Eswatini
tc|Turks a Caicos
td|Čad
tf|Francouzská jižní území
tg|Togo
th|Thajsko
tj|Tádžikistán
tk|Tokelau
tl|Východní Timor
tm|Turkmenistán
tn|Tunisko
to|Tonga
tr|Turecko
tt|Trinidad a Tobago
tv|Tuvalu
tw|Tchaj-wan
tz|Tanzanie
ua|Ukrajina
ug|Uganda
um|Menší odlehlé ostrovy USA
us|Spojené státy
uy|Uruguay
uz|Uzbekistán
va|Vatikán
vc|Svatý Vincenc a Grenadiny
ve|Venezuela
vg|Britské Panenské ostrovy
vi|Americké Panenské ostrovy
vn|Vietnam
vu|Vanuatu
wf|Wallis a Futuna
ws|Samoa
xk|Kosovo
ye|Jemen
yt|Mayotte
za|Jihoafrická republika
zm|Zambie
zw|Zimbabwe""".splitlines())
POPULAR = ("cz", "gb-eng", "jp", "br", "ch", "np", "sa")


def search_key(text):
    return "".join(c for c in unicodedata.normalize("NFD", text.casefold())
                   if not unicodedata.combining(c))


def load_flags():
    downloaded = not ARCHIVE.is_file()
    if downloaded:
        with urllib.request.urlopen(FLAG_URL, timeout=20) as response:
            data = response.read()
    else:
        data = ARCHIVE.read_bytes()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        flags = {Path(name).stem: archive.read(name).decode("utf-8-sig")
                 for name in archive.namelist() if name.endswith(".svg")}
    if "cz" not in flags:
        raise ValueError("Archiv musí obsahovat soubor cz.svg.")
    if downloaded:
        try:
            ARCHIVE.write_bytes(data)
        except OSError:
            pass  # Pro aktuální relaci stačí archiv v paměti.
    return flags


@lru_cache(maxsize=512)
def source_geometry(source):
    root = ET.fromstring(source)
    try:
        return (float(root.attrib["width"].removesuffix("px")),
                float(root.attrib["height"].removesuffix("px")))
    except (KeyError, ValueError):
        _, _, width, height = map(float, root.attrib["viewBox"].replace(",", " ").split())
        return width, height


@lru_cache(maxsize=48)
def render_flag(source, width):
    original_width, original_height = source_geometry(source)
    height = max(1, round(width * original_height / original_width))
    png = resvg_py.svg_to_bytes(svg_string=source, width=width, height=height)
    with Image.open(io.BytesIO(png)) as image:
        return image.convert("RGBA")


def raster_tile(flag, mirror):
    if not mirror:
        return flag
    w, h = flag.size
    tile = Image.new("RGBA", (2 * w, 2 * h))
    horizontal = ImageOps.mirror(flag)
    for image, position in ((flag, (0, 0)), (horizontal, (w, 0)),
                            (ImageOps.flip(flag), (0, h)),
                            (ImageOps.flip(horizontal), (w, h))):
        tile.paste(image, position)
    return tile


def repeat_image(tile, columns, rows):
    w, h = tile.size
    image = Image.new("RGBA", (columns * w, rows * h))
    for y in range(rows):
        for x in range(columns):
            image.paste(tile, (x * w, y * h))
    return image


def edge_matches(tile):
    w, h = tile.size
    left_right = tile.crop((0, 0, 1, h)).tobytes() == tile.crop((w-1, 0, w, h)).tobytes()
    top_bottom = tile.crop((0, 0, w, 1)).tobytes() == tile.crop((0, h-1, w, h)).tobytes()
    return left_right, top_bottom


def vector_pattern(source, width, mirror, columns=1, rows=1):
    """Samostatné SVG s vloženou vlajkou a transformovanými odkazy <use>."""
    original_width, original_height = source_geometry(source)
    height = width * original_height / original_width
    period = 2 if mirror else 1
    w, h = width * period * columns, height * period * rows
    def number(value):
        return format(value, ".15g")

    root = ET.Element(f"{{{SVG}}}svg", width=number(w), height=number(h),
                      viewBox=f"0 0 {number(w)} {number(h)}")
    defs = ET.SubElement(root, f"{{{SVG}}}defs")
    flag = ET.fromstring(source)
    flag.attrib.setdefault("viewBox", f"0 0 {number(original_width)} {number(original_height)}")
    flag.set("width", number(width))
    flag.set("height", number(height))
    existing_ids = {element.get("id") for element in flag.iter()}
    flag_id = "teselace-vlajka"
    while flag_id in existing_ids:
        flag_id += "-1"
    group = ET.SubElement(defs, f"{{{SVG}}}g", id=flag_id)
    group.append(flag)
    for y in range(period * rows):
        for x in range(period * columns):
            flip_x, flip_y = mirror and x % 2, mirror and y % 2
            tx, ty = (x + flip_x) * width, (y + flip_y) * height
            ET.SubElement(root, f"{{{SVG}}}use", {
                f"{{{XLINK}}}href": f"#{flag_id}",
                "transform": f"translate({number(tx)} {number(ty)}) scale({1-2*flip_x} {1-2*flip_y})",
            })
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


class App:
    def __init__(self, root):
        self.root = root
        root.title("Teselace vlajek")
        root.geometry("1020x660")
        root.minsize(650, 435)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)
        self.flags = {}
        self.visible_codes = []
        self.current_code = "cz"
        self.tile = None
        self.photo = None
        self.pending_draw = None
        self.search = tk.StringVar()
        self.size = tk.IntVar(value=135)
        self.mirror = tk.BooleanVar(value=True)
        self.single = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Načítám katalog vlajek…")

        sidebar = ttk.Frame(root, padding=14)
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.columnconfigure(0, weight=1)
        sidebar.rowconfigure(3, weight=1)
        ttk.Label(sidebar, text="Teselace vlajek", font=("TkDefaultFont", 16, "bold")).grid(sticky="w")
        ttk.Label(sidebar, text="Hledat zemi nebo kód").grid(sticky="w", pady=(12, 2))
        self.entry = ttk.Entry(sidebar, textvariable=self.search)
        self.entry.grid(sticky="ew")
        list_frame = ttk.Frame(sidebar)
        list_frame.grid(sticky="nsew", pady=(4, 8))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        self.listbox = tk.Listbox(list_frame, width=29, exportselection=False, activestyle="none")
        self.listbox.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.listbox.configure(yscrollcommand=scroll.set)
        self.listbox.bind("<<ListboxSelect>>", self.select_flag)
        self.entry.bind("<Down>", self.focus_list)
        self.entry.bind("<Return>", self.choose_first)
        self.search.trace_add("write", lambda *_: self.filter_flags())

        ttk.Checkbutton(sidebar, text="Zrcadlit vodorovně i svisle", variable=self.mirror,
                        command=self.schedule_draw).grid(sticky="w")
        ttk.Label(sidebar, text="Vypni pro zachování směru nápisů.\nHrany pak mohou mít barevný skok.",
                  justify="left").grid(sticky="w", pady=(2, 8))
        self.size_label = ttk.Label(sidebar)
        self.size_label.grid(sticky="w")
        tk.Scale(sidebar, from_=36, to=320, orient="horizontal", showvalue=False,
                 variable=self.size, command=self.schedule_draw, highlightthickness=0).grid(sticky="ew")
        ttk.Checkbutton(sidebar, text="Ukázat jen základní dlaždici", variable=self.single,
                        command=self.schedule_draw).grid(sticky="w", pady=(5, 8))
        self.scope = ttk.Combobox(sidebar, state="readonly", values=("Základní dlaždice", "Vzor 4 × 3"))
        self.scope.current(0)
        self.scope.grid(sticky="ew")
        buttons = ttk.Frame(sidebar)
        buttons.grid(sticky="ew", pady=(4, 0))
        self.export_buttons = []
        for column, extension in enumerate(("svg", "png")):
            buttons.columnconfigure(column, weight=1)
            button = ttk.Button(buttons, text=f"Uložit {extension.upper()}", state="disabled",
                                command=lambda ext=extension: self.save(ext))
            button.grid(row=0, column=column, sticky="ew", padx=2)
            self.export_buttons.append(button)

        self.canvas = tk.Canvas(root, bg="#e5e7eb", highlightthickness=0)
        self.canvas.grid(row=0, column=1, sticky="nsew", padx=(0, 12), pady=(12, 4))
        self.canvas.bind("<Configure>", self.schedule_draw)
        ttk.Label(root, textvariable=self.status, padding=(14, 6)).grid(row=1, columnspan=2, sticky="w")
        self.results = queue.Queue()
        threading.Thread(target=self.fetch_catalog, daemon=True).start()
        root.after(40, self.receive_catalog)
        self.entry.focus_set()

    def fetch_catalog(self):
        try:
            self.results.put((load_flags(), None))
        except Exception as error:
            self.results.put(({}, str(error)))

    def receive_catalog(self):
        try:
            self.flags, error = self.results.get_nowait()
        except queue.Empty:
            self.root.after(40, self.receive_catalog)
            return
        if error:
            self.status.set("Katalog se nepodařilo načíst.")
            messagebox.showerror("Katalog vlajek", f"{error}\n\nZkus aplikaci spustit znovu s internetem nebo ulož archiv z {FLAG_URL} vedle skriptu jako vlajky.zip.")
            return
        self.filter_flags()
        self.schedule_draw()

    def filter_flags(self):
        query = search_key(self.search.get().strip())
        codes = [code for code in self.flags
                 if query in search_key(f"{COUNTRIES.get(code, '')} {code}")]
        self.visible_codes = sorted(codes, key=lambda code: (
            bool(query) and query not in (code, search_key(COUNTRIES.get(code, ""))),
            POPULAR.index(code) if not query and code in POPULAR else len(POPULAR),
            search_key(COUNTRIES.get(code, code))))
        self.listbox.delete(0, "end")
        for code in self.visible_codes:
            self.listbox.insert("end", f"{COUNTRIES.get(code, code)}  ·  {code.upper()}")
        if self.current_code in self.visible_codes:
            index = self.visible_codes.index(self.current_code)
            self.listbox.selection_set(index)
            self.listbox.see(index)

    def choose_first(self, _event=None):
        if self.visible_codes:
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(0)
            self.listbox.activate(0)
            self.select_flag()

    def focus_list(self, _event):
        if not self.listbox.curselection():
            self.choose_first()
        self.listbox.focus_set()
        return "break"

    def select_flag(self, _event=None):
        selection = self.listbox.curselection()
        if selection:
            self.current_code = self.visible_codes[selection[0]]
            self.schedule_draw()

    def schedule_draw(self, _event=None):
        if self.pending_draw is not None:
            self.root.after_cancel(self.pending_draw)
        self.pending_draw = self.root.after(25, self.draw)

    def current_tile(self):
        return raster_tile(render_flag(self.flags[self.current_code], self.size.get()), self.mirror.get())

    def draw(self):
        self.pending_draw = None
        self.size_label.configure(text=f"Šířka jedné vlajky  ·  {self.size.get()} px")
        if not self.flags:
            return
        self.canvas.delete("all")
        try:
            self.tile = self.current_tile()
        except (ValueError, RuntimeError, OSError, KeyError, ET.ParseError) as error:
            self.tile = None
            for button in self.export_buttons:
                button.state(["disabled"])
            self.status.set(f"Vlajku nelze vykreslit. {error}")
            return
        for button in self.export_buttons:
            button.state(["!disabled"])
        w, h = self.tile.size
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        if self.single.get():
            image = self.tile.copy()
            image.thumbnail((max(1, cw-24), max(1, ch-24)), Image.Resampling.LANCZOS)
        else:
            image = repeat_image(self.tile, math.ceil(cw / w), math.ceil(ch / h))
            image = image.crop((0, 0, cw, ch))
        self.photo = ImageTk.PhotoImage(image)
        self.canvas.create_image(cw//2, ch//2, image=self.photo)
        lr, tb = edge_matches(self.tile)
        name = COUNTRIES.get(self.current_code, self.current_code.upper())
        self.status.set(f"{name}   ·   Dlaždice {w} × {h} px   ·   "
                        f"Levá/pravá {'✓' if lr else '≠'}   Horní/dolní {'✓' if tb else '≠'}")

    def save(self, extension):
        columns, rows = (4, 3) if self.scope.current() == 1 else (1, 1)
        kind = "vzor" if columns > 1 else "dlazdice"
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=f".{extension}",
            initialfile=f"{self.current_code}-{kind}.{extension}",
            filetypes=[(extension.upper(), f"*.{extension}")])
        if not path:
            return
        try:
            if extension == "svg":
                svg = vector_pattern(self.flags[self.current_code], self.size.get(),
                                     self.mirror.get(), columns, rows)
                Path(path).write_bytes(svg)
            else:
                repeat_image(self.current_tile(), columns, rows).save(path, format="PNG")
        except (OSError, ValueError, RuntimeError, KeyError, ET.ParseError) as error:
            messagebox.showerror("Export se nezdařil", str(error), parent=self.root)


if __name__ == "__main__":
    window = tk.Tk()
    App(window)
    window.mainloop()
