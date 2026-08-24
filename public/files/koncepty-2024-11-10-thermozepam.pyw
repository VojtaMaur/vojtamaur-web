import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk
import numpy as np
import tifffile as tiff
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import json
import tkinter.font as tkFont
from json.decoder import JSONDecodeError

class CustomCombobox(ttk.Combobox):
    def __init__(self, master=None, **kwargs):
        ttk.Combobox.__init__(self, master, **kwargs)
        self.bind('<Button-1>', self.on_click)
        self.listbox_images = []
        self.menu = None

    def on_click(self, event):
        if self.menu is not None:
            self.menu.destroy()
        self.menu = tk.Toplevel(self)
        self.menu.wm_overrideredirect(True)
        self.menu.wm_geometry("+%d+%d" % (self.winfo_rootx(), self.winfo_rooty() + self.winfo_height()))
        frame = tk.Frame(self.menu, borderwidth=1, relief="solid")
        frame.pack(fill="both", expand=True)
        self.populate_menu(frame)
        return "break"  # Zastaví další zpracování události

    def populate_menu(self, frame):
        canvas = tk.Canvas(frame)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(
                scrollregion=canvas.bbox("all")
            )
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # Nastavení posunu kolečkem myši
        canvas.bind_all("<MouseWheel>", lambda event: canvas.yview_scroll(int(-1*(event.delta/120)), "units"))
        canvas.bind_all("<Button-4>", lambda event: canvas.yview_scroll(-1, "units"))
        canvas.bind_all("<Button-5>", lambda event: canvas.yview_scroll(1, "units"))

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        heading_font = tkFont.Font(weight='bold')

        for item in self["values"]:
            if item in ["OBLÍBENÉ", "OSTATNÍ"]:
                label = tk.Label(scrollable_frame, text=item, font=heading_font, background='lightgray')
                label.pack(fill="x")
            else:
                frame_item = tk.Frame(scrollable_frame)
                frame_item.pack(fill="x", padx=2, pady=2)

                # Vytvoření náhledu spektra
                cmap = cm.get_cmap(item)
                gradient = np.linspace(0, 1, 256).reshape(1, -1)
                gradient_img = cmap(gradient)
                plt.imsave("temp_preview.png", gradient_img, format='png')
                preview_image = Image.open("temp_preview.png").resize((50, 20), Image.LANCZOS)
                img = ImageTk.PhotoImage(preview_image)
                self.listbox_images.append(img)  # Udržujeme referenci na obrázek

                label_image = tk.Label(frame_item, image=img)
                label_image.pack(side="left")

                label_text = tk.Label(frame_item, text=item)
                label_text.pack(side="left", padx=5)

                frame_item.bind("<Button-1>", lambda e, val=item: self.select_value(val))
                label_image.bind("<Button-1>", lambda e, val=item: self.select_value(val))
                label_text.bind("<Button-1>", lambda e, val=item: self.select_value(val))

                os.remove("temp_preview.png")

    def select_value(self, value):
        self.set(value)
        self.event_generate("<<ComboboxSelected>>")
        self.menu.destroy()


class ImageViewer:
    def __init__(self, master):
        self.master = master
        self.master.title("THERMOZEPAM - termografický prohlížeč editor")
        self.master.geometry("1200x800")
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.master.bind("<KeyPress-f>", self.toggle_fullscreen)
        self.master.bind("<Escape>", self.end_fullscreen)
        self.master.bind("<Left>", lambda event: self.show_prev_image())
        self.master.bind("<Right>", lambda event: self.show_next_image())
        self.master.bind("<Up>", lambda event: self.change_colormap(1))
        self.master.bind("<Down>", lambda event: self.change_colormap(-1))
        self.master.bind("i", lambda event: self.toggle_reverse_colormap())
        self.fullscreen = False

        # Fonty pro labely a hodnoty
        label_font = tkFont.Font(family="Helvetica", size=14)
        value_font = tkFont.Font(family="Helvetica", size=12, weight="bold")

        # Frame pro horní ovládací prvky
        top_control_frame = tk.Frame(master)
        top_control_frame.pack(side=tk.TOP, pady=10)

        # Tlačítka nahoře
        button_width = 15

        open_button = tk.Button(top_control_frame, text="Otevřít složku", width=button_width, command=self.open_folder)
        open_button.pack(side=tk.LEFT, padx=5)

        save_button = tk.Button(top_control_frame, text="Uložit obrázek", width=button_width, command=self.save_image)
        save_button.pack(side=tk.LEFT, padx=5)

        # Checkbox pro zvýšení rozlišení
        self.upscale_var = tk.BooleanVar(value=True)
        upscale_checkbox = tk.Checkbutton(top_control_frame, text="Zvýšit rozlišení", variable=self.upscale_var)
        upscale_checkbox.pack(side=tk.LEFT, padx=5)

        colormap_label = tk.Label(top_control_frame, text="Barevné spektrum:")
        colormap_label.pack(side=tk.LEFT, padx=5)

        # Načtení oblíbených spekter ze souboru
        self.favorite_colormaps = self.load_favorite_colormaps()

        # Výběr colormap
        self.additional_colormaps = [cmap for cmap in plt.colormaps() if cmap not in self.favorite_colormaps]
        self.all_colormaps = ["OBLÍBENÉ"] + self.favorite_colormaps + ["OSTATNÍ"] + self.additional_colormaps
        self.selected_colormap = tk.StringVar(value=self.favorite_colormaps[0])

        # Vytvoření CustomCombobox
        self.colormap_menu = CustomCombobox(top_control_frame, textvariable=self.selected_colormap, width=40, state="readonly")
        self.colormap_menu.pack(side=tk.LEFT, padx=5)
        self.colormap_menu['values'] = self.all_colormaps
        self.selected_colormap.trace('w', self.update_image)

        # Hlavní frame pro obrázek a spektrum
        main_frame = tk.Frame(master)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Frame pro spektrum a popisky (vlevo)
        self.spectrum_frame = tk.Frame(main_frame)
        self.spectrum_frame.grid(row=0, column=0, padx=10, pady=10, sticky="n")

        # Frame pro obrázek (vycentrovaný a nezávislý na spektru)
        self.image_frame = tk.Frame(main_frame)
        self.image_frame.grid(row=0, column=1, sticky="nsew")
        main_frame.grid_columnconfigure(1, weight=1)
        main_frame.grid_rowconfigure(0, weight=1)

        self.image_label = tk.Label(self.image_frame)
        self.image_label.place(x=0, y=0)
        self.image_label.bind("<Button-1>", self.show_temperature)
        self.image_label.bind("<B1-Motion>", self.show_temperature)

        # Frame pro teploty, zarovnané napravo od fotografie
        temperature_frame = tk.Frame(main_frame)
        temperature_frame.grid(row=0, column=2, padx=10, sticky="n")

        self.temperature_label = tk.Label(temperature_frame, text="Teplota vybraného bodu:", font=label_font)
        self.temperature_label.pack(anchor="w")

        self.temperature_value_label = tk.Label(temperature_frame, text="Bod není zvolen", font=value_font)
        self.temperature_value_label.pack(anchor="w")

        self.average_temperature_label = tk.Label(temperature_frame, text="Průměrná teplota fotografie:", font=label_font)
        self.average_temperature_label.pack(anchor="w")

        self.average_temperature_value_label = tk.Label(temperature_frame, text="N/A", font=value_font)
        self.average_temperature_value_label.pack(anchor="w")

        # Modus teploty fotografie
        self.mode_temperature_label = tk.Label(temperature_frame, text="Modus teploty fotografie:", font=label_font)
        self.mode_temperature_label.pack(anchor="w")

        self.mode_temperature_value_label = tk.Label(temperature_frame, text="N/A", font=value_font)
        self.mode_temperature_value_label.pack(anchor="w")
        

        # Oddělovač mezi teplotními údaji a dalšími informacemi
        separator = tk.Label(temperature_frame, text=" " * 3)
        separator.pack(anchor="w")

        # Čas pořízení, název fotografie a cesta ke složce
        self.capture_time_label = tk.Label(temperature_frame, text="Čas pořízení:", font=label_font)
        self.capture_time_label.pack(anchor="w")

        self.capture_time_value_label = tk.Label(temperature_frame, text="N/A", font=value_font)
        self.capture_time_value_label.pack(anchor="w")
        

        # Přidat prázdný řádek
        empty_label = tk.Label(temperature_frame, text="")
        empty_label.pack()

        self.image_name_label = tk.Label(temperature_frame, text="Název fotografie:", font=label_font)
        self.image_name_label.pack(anchor="w")

        self.image_name_value_label = tk.Label(temperature_frame, text="N/A", font=value_font)
        self.image_name_value_label.pack(anchor="w")
        
        self.folder_path_label = tk.Label(temperature_frame, text="   ", font=label_font)#mezera

        # Přidat prázdný řádek
        empty_label = tk.Label(temperature_frame, text="")
        empty_label.pack()

        self.folder_path_label = tk.Label(temperature_frame, text="Složka:", font=label_font)
        self.folder_path_label.pack(anchor="w")

        self.folder_path_value_label = tk.Label(temperature_frame, text="N/A", font=value_font)
        self.folder_path_value_label.pack(anchor="w")

        # Control frame pro tlačítka "Předchozí" a "Další" pod obrázkem, centrovaný s obrázkem
        nav_frame = tk.Frame(main_frame)
        nav_frame.grid(row=1, column=1, pady=10)

        prev_button = tk.Button(nav_frame, text="Předchozí", width=button_width, command=self.show_prev_image)
        prev_button.pack(side=tk.LEFT, padx=5)

        # Počítadlo aktuálního obrázku
        self.image_counter_label = tk.Label(nav_frame, text="0/0", font=("Helvetica", 12))
        self.image_counter_label.pack(side=tk.LEFT, padx=5)

        next_button = tk.Button(nav_frame, text="Další", width=button_width, command=self.show_next_image)
        next_button.pack(side=tk.LEFT, padx=5)

        # Inicializace proměnných
        self.config_path = "config.json"
        self.folder_path = ''
        self.save_folder_path = ''
        self.image_files = []
        self.current_index = 0
        self.reverse_colormap = False
        self.image_array = None
        self.original_pil_image = None

        # Načtení konfigurace
        self.load_config()
        if self.folder_path:
            self.load_images()
            self.show_image()

        # Bind resize event to image frame
        self.image_frame.bind("<Configure>", self.on_resize)

    def load_favorite_colormaps(self):
        """Načte oblíbená spektra z favourite_spectrums.txt. Pokud soubor neexistuje nebo je prázdný, použije výchozí hodnoty."""
        favorite_colormaps = []
        try:
            with open("favourite_spectrums.txt", "r") as file:
                favorite_colormaps = [line.strip() for line in file if line.strip()]
        except FileNotFoundError:
            pass

        # Pokud je seznam prázdný, nastavíme výchozí hodnoty
        if not favorite_colormaps:
            favorite_colormaps = ["twilight", "twilight_shifted", "binary", "RdYlBu", "plasma",
                                  "CMRmap", "hot", "Accent", "flag"]

        return favorite_colormaps

    def toggle_fullscreen(self, event=None):
        self.fullscreen = not self.fullscreen
        self.master.attributes("-fullscreen", self.fullscreen)

    def end_fullscreen(self, event=None):
        self.fullscreen = False
        self.master.attributes("-fullscreen", False)

    def load_config(self):
        """Načtení konfigurace z config.json s ošetřením chyb"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as file:
                    config = json.load(file)
                    self.folder_path = config.get("last_opened_folder", "")
                    self.save_folder_path = config.get("last_save_folder", "")
                    self.current_index = config.get("last_image_index", 0)

                    if not os.path.isdir(self.folder_path):
                        self.folder_path = ""
                        self.current_index = 0
                    if not os.path.isdir(self.save_folder_path):
                        self.save_folder_path = ""

                    last_colormap = config.get("last_colormap", self.favorite_colormaps[0])
                    if last_colormap not in ["OBLÍBENÉ", "OSTATNÍ"]:
                        self.selected_colormap.set(last_colormap)
                    else:
                        self.selected_colormap.set(self.favorite_colormaps[0])

                    self.reverse_colormap = config.get("reverse_colormap", False)
            except (JSONDecodeError, Exception):
                os.remove(self.config_path)
                self.folder_path = ''
                self.save_folder_path = ''
                self.current_index = 0
                self.reverse_colormap = False
                self.selected_colormap.set(self.favorite_colormaps[0])
        else:
            self.folder_path = ''
            self.save_folder_path = ''
            self.current_index = 0
            self.reverse_colormap = False
            self.selected_colormap.set(self.favorite_colormaps[0])

    def save_config(self):
        """Uložení konfigurace do config.json"""
        selected_colormap = self.selected_colormap.get()
        if selected_colormap in ["OBLÍBENÉ", "OSTATNÍ"]:
            selected_colormap = self.favorite_colormaps[0] if self.favorite_colormaps else "viridis"

        config = {
            "last_opened_folder": self.folder_path,
            "last_save_folder": self.save_folder_path,
            "last_colormap": selected_colormap,
            "reverse_colormap": self.reverse_colormap,
            "last_image_index": self.current_index
        }
        with open(self.config_path, "w") as file:
            json.dump(config, file)

    def on_closing(self):
        """Při zavření aplikace"""
        self.save_config()
        self.master.destroy()

    def open_folder(self):
        """Otevře dialog pro výběr složky"""
        folder = filedialog.askdirectory(initialdir=self.folder_path or os.getcwd())
        if folder:
            if folder != self.folder_path:
                self.current_index = 0

            self.folder_path = folder
            self.save_config()
            self.load_images()
            self.show_image()

    def load_images(self):
        files = os.listdir(self.folder_path)
        self.image_files = [f for f in files if f.lower().endswith('.tiff')]
        self.image_files.sort()
        self.update_image_counter()

    def show_image(self):
        if self.image_files:
            tiff_path = os.path.join(self.folder_path, self.image_files[self.current_index])
            image = tiff.imread(tiff_path, key=1)
            self.image_array = np.array(image)
            self.image_array = np.rot90(self.image_array, k=1)

            # Výpočet průměrné teploty
            self.average_temperature = np.mean(self.image_array)
            self.average_temperature_value_label.config(text=f"{self.average_temperature:.2f} °C")

            # Výpočet min a max teploty
            min_temp = np.min(self.image_array)
            max_temp = np.max(self.image_array)
            temp_range = max_temp - min_temp

            # Rozhodnutí o počtu desetinných míst pro zaokrouhlení
            if temp_range <= 10:
                decimals = 1
            else:
                decimals = 0

            # Zaokrouhlení hodnot pro výpočet modusu
            rounded_temps = np.round(self.image_array, decimals=decimals)
            values, counts = np.unique(rounded_temps, return_counts=True)
            index = np.argmax(counts)
            self.mode_temperature = values[index]

            # Zobrazení modusu s nebo bez desetinných míst
            if decimals == 0 or self.mode_temperature % 1 == 0:
                mode_str = f"{int(self.mode_temperature)} °C"
            else:
                mode_str = f"{self.mode_temperature:.1f} °C"

            self.mode_temperature_value_label.config(text=mode_str)

            # Čas pořízení
            metadata = tiff.TiffFile(tiff_path).pages[0].tags
            datetime_tag = metadata.get("DateTime")
            if datetime_tag:
                self.capture_time_value_label.config(text=datetime_tag.value)
            else:
                self.capture_time_value_label.config(text="Neznámý")

            # Název fotografie
            self.image_name_value_label.config(text=self.image_files[self.current_index])

            # Složka fotografií
            self.folder_path_value_label.config(text=self.folder_path)

            # Reset teploty vybraného bodu
            self.temperature_value_label.config(text="Bod není zvolen")

            # Aktualizace počítadla
            self.update_image_counter()

            # Generování obrázku
            self.generate_pil_image()

            # Zobrazení obrázku
            self.display_image()

            # Aktualizace spektra a histogramu
            self.display_spectrum()
        else:
            self.image_label.configure(image='', text='Žádné obrázky nenalezeny.')
            self.original_pil_image = None

    def display_spectrum(self):
        """Vytvoří a zobrazí vertikální spektrum s popisky pro min a max hodnoty a histogram teplot"""
        colormap = self.get_current_colormap()
        if colormap is None:
            return

        # Definice požadované šířky a výšky histogramu
        histogram_width_px = 150  # Požadovaná šířka histogramu v pixelech
        histogram_height_px = 300  # Výška histogramu
        dpi = 500  # Rozlišení obrázku

        # Vytvoření vertikálního gradientu pro spektrum bez rotace
        gradient = np.linspace(1, 0, 256).reshape(-1, 1)  # Vytvoří gradient s max nahoře, min dole
        gradient_img = cm.get_cmap(colormap)(gradient)

        # Uložení obrázku spektra bez rotace a vertikálního flipu
        plt.imsave("temp_spectrum.png", gradient_img, format='png')
        spectrum_image = Image.open("temp_spectrum.png").resize((50, histogram_height_px), Image.LANCZOS)
        tk_spectrum_image = ImageTk.PhotoImage(spectrum_image)

        os.remove("temp_spectrum.png")

        # Generování histogramu s počty pixelů reprezentovanými šířkou pruhů
        num_bins = 256  # Stejný počet binů jako výška spektra
        counts, bin_edges = np.histogram(self.image_array.flatten(), bins=num_bins, range=(self.image_array.min(), self.image_array.max()))

        # Normalizace counts pro zobrazení
        counts_normalized = counts / counts.max()

        # Vytvoření obrázku histogramu s požadovanou velikostí
        fig_width_in = histogram_width_px / dpi
        fig_height_in = histogram_height_px / dpi

        fig, ax = plt.subplots(figsize=(fig_width_in, fig_height_in), dpi=dpi)
        fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

        # Mapování teplot na barvy
        cmap = cm.get_cmap(colormap)
        norm = plt.Normalize(vmin=self.image_array.min(), vmax=self.image_array.max())
        colors = cmap(norm((bin_edges[:-1] + bin_edges[1:]) / 2))

        # Vykreslení vertikálního histogramu bez inverze osy y
        ax.barh(
            y=bin_edges[:-1],
            width=counts_normalized,
            height=(bin_edges[1] - bin_edges[0]),
            color=colors,
            edgecolor='none',
            align='edge'
        )

        ax.axis('off')

        # Uložení obrázku histogramu
        plt.savefig('temp_histogram.png', bbox_inches='tight', pad_inches=0)
        plt.close()

        # Načtení obrázku histogramu (není potřeba měnit velikost)
        hist_image = Image.open('temp_histogram.png')
        tk_hist_image = ImageTk.PhotoImage(hist_image)

        os.remove('temp_histogram.png')

        # Aktualizace popisků min/max teplot s aktuálními hodnotami
        min_temp = np.min(self.image_array)
        max_temp = np.max(self.image_array)

        # Vyčištění předchozích widgetů ve frame
        for widget in self.spectrum_frame.winfo_children():
            widget.destroy()

        # Vytvoření nového frame pro popisky a spektrum
        labels_spectrum_frame = tk.Frame(self.spectrum_frame)
        labels_spectrum_frame.pack(side=tk.LEFT)

        # Frame pro max label a spektrum
        max_label_spectrum_frame = tk.Frame(labels_spectrum_frame)
        max_label_spectrum_frame.pack(side=tk.LEFT)

        # Max label
        self.max_temp_label = tk.Label(max_label_spectrum_frame, text=f"{max_temp:.2f} °C", font=("Helvetica", 12, "bold"))
        self.max_temp_label.pack()

        # Spektrum
        self.spectrum_label = tk.Label(max_label_spectrum_frame, image=tk_spectrum_image)
        self.spectrum_label.image = tk_spectrum_image
        self.spectrum_label.pack()

        # Min label
        self.min_temp_label = tk.Label(max_label_spectrum_frame, text=f"{min_temp:.2f} °C", font=("Helvetica", 12, "bold"))
        self.min_temp_label.pack()

        # Histogram vedle spektra
        self.histogram_label = tk.Label(labels_spectrum_frame, image=tk_hist_image)
        self.histogram_label.image = tk_hist_image
        self.histogram_label.pack(side=tk.LEFT)


    def update_image_counter(self):
        total_images = len(self.image_files)
        current_image = self.current_index + 1
        self.image_counter_label.config(text=f"{current_image}/{total_images}")

    def show_prev_image(self):
        if self.image_files:
            self.current_index = (self.current_index - 1) % len(self.image_files)
            self.show_image()

    def show_next_image(self):
        if self.image_files:
            self.current_index = (self.current_index + 1) % len(self.image_files)
            self.show_image()

    def change_colormap(self, step):
        all_colormaps = [c for c in self.all_colormaps if c not in ["OBLÍBENÉ", "OSTATNÍ"]]
        current_index = all_colormaps.index(self.selected_colormap.get())
        new_index = (current_index + step) % len(all_colormaps)
        self.selected_colormap.set(all_colormaps[new_index])
        self.show_image()

    def toggle_reverse_colormap(self):
        self.reverse_colormap = not self.reverse_colormap
        base_colormap_name = self.selected_colormap.get().replace("_inverted", "")
        if self.reverse_colormap:
            self.selected_colormap.set(f"{base_colormap_name}_inverted")
        else:
            self.selected_colormap.set(base_colormap_name)
        self.show_image()

    def update_image(self, *args):
        selected = self.selected_colormap.get()
        if selected not in ["OBLÍBENÉ", "OSTATNÍ"]:
            self.show_image()

    def show_temperature(self, event):
        if self.image_array is not None:
            widget_width, widget_height = self.image_label.winfo_width(), self.image_label.winfo_height()
            orig_height, orig_width = self.image_array.shape
            x_ratio = orig_width / widget_width
            y_ratio = orig_height / widget_height

            x = int(event.x * x_ratio)
            y = int(event.y * y_ratio)

            if 0 <= x < orig_width and 0 <= y < orig_height:
                temperature = self.image_array[y, x]
                self.temperature_value_label.config(text=f"{temperature:.2f} °C")

    def save_image(self):
        if self.image_files:
            tiff_path = os.path.join(self.folder_path, self.image_files[self.current_index])
            image = tiff.imread(tiff_path, key=1)
            image_array = np.array(image)
            image_array = np.rot90(image_array, k=1)

            # Normalizace a aplikace colormap
            colormap = self.get_current_colormap()
            if colormap is None:
                return
            normalized_img = (image_array - image_array.min()) / (image_array.max() - image_array.min())
            cmap = cm.get_cmap(colormap)
            colored_img = cmap(normalized_img)[:, :, :3]
            pil_image = Image.fromarray((colored_img * 255).astype(np.uint8))

            # Kontrola checkboxu pro zvýšení rozlišení
            if self.upscale_var.get():
                scale_factor = 6  # Můžete upravit měřítko podle potřeby
                new_size = (pil_image.width * scale_factor, pil_image.height * scale_factor)
                pil_image = pil_image.resize(new_size, Image.BICUBIC)

            # Uložení obrázku
            save_path = filedialog.asksaveasfilename(
                initialdir=self.save_folder_path or os.getcwd(),
                defaultextension='.png',
                filetypes=[('PNG files', '*.png')]
            )
            if save_path:
                pil_image.save(save_path)
                self.save_folder_path = os.path.dirname(save_path)
                self.save_config()

    def generate_pil_image(self):
        colormap = self.get_current_colormap()
        if colormap is None:
            return
        normalized_img = (self.image_array - self.image_array.min()) / (self.image_array.max() - self.image_array.min())
        cmap = cm.get_cmap(colormap)
        colored_img = cmap(normalized_img)[:, :, :3]
        self.original_pil_image = Image.fromarray((colored_img * 255).astype(np.uint8))

    def get_current_colormap(self):
        colormap = self.selected_colormap.get()
        if colormap in ["OBLÍBENÉ", "OSTATNÍ"]:
            colormap = self.favorite_colormaps[0] if self.favorite_colormaps else "viridis"
        colormap = colormap.replace("_inverted", "")
        if self.reverse_colormap:
            colormap += "_r"
        return colormap

    def display_image(self):
        if self.original_pil_image:
            window_width, window_height = self.image_frame.winfo_width(), self.image_frame.winfo_height()
            aspect_ratio = self.original_pil_image.width / self.original_pil_image.height

            if window_width / window_height < aspect_ratio:
                new_width = window_width
                new_height = int(window_width / aspect_ratio)
            else:
                new_height = window_height
                new_width = int(window_height * aspect_ratio)

            new_width = max(1, new_width)
            new_height = max(1, new_height)

            pil_image = self.original_pil_image.resize((new_width, new_height), Image.LANCZOS)
            tk_image = ImageTk.PhotoImage(pil_image)

            self.image_label.configure(image=tk_image)
            self.image_label.image = tk_image
            self.image_label.place(x=(window_width - new_width) // 2, y=(window_height - new_height) // 2)

    def on_resize(self, event):
        self.display_image()

if __name__ == "__main__":
    root = tk.Tk()
    try:
        app = ImageViewer(root)
        root.mainloop()
    except Exception as e:
        messagebox.showerror("Chyba", f"Došlo k neočekávané chybě: {str(e)}")
