import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import struct
import os
import subprocess
import sys
from pathlib import Path
from PIL import Image, ImageTk
import numpy as np

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

COLOR_BG = "#0a0a0a"
COLOR_SURFACE = "#161616"
COLOR_ACCENT = "#005a9e"
COLOR_TEXT = "#d0d0d0"
COLOR_TEXT_DIM = "#707070"
COLOR_BTN = "#2a2a2a"
COLOR_BTN_HOVER = "#3a3a3a"
COLOR_ERROR = "#cf6679"
COLOR_MODIFIED = "#b00020"

FONT_S = ("Segoe UI", 9)
FONT_M = ("Segoe UI", 10)
FONT_B = ("Segoe UI", 11, "bold")
FONT_TITLE = ("Segoe UI", 22, "bold")
FONT_MONO = ("Consolas", 9)

def apply_modern_style():
    style = ttk.Style()
    style.theme_use('clam')
    style.configure(".", background=COLOR_BG, foreground=COLOR_TEXT, font=FONT_M, borderwidth=0)
    style.configure("TFrame", background=COLOR_BG)
    style.configure("Surface.TFrame", background=COLOR_SURFACE)
    style.configure("TLabel", background=COLOR_BG, foreground=COLOR_TEXT)
    style.configure("Surface.TLabel", background=COLOR_SURFACE, foreground=COLOR_TEXT)
    style.configure("Title.TLabel", foreground=COLOR_ACCENT, font=FONT_TITLE)
    style.configure("TButton", background=COLOR_BTN, foreground=COLOR_TEXT, borderwidth=0, padding=8, focuscolor=COLOR_ACCENT)
    style.map("TButton", background=[('active', COLOR_BTN_HOVER), ('disabled', COLOR_BG)], foreground=[('disabled', COLOR_TEXT_DIM)])
    style.configure("Treeview", background=COLOR_SURFACE, foreground=COLOR_TEXT, fieldbackground=COLOR_SURFACE, rowheight=30)
    style.map("Treeview", background=[('selected', COLOR_ACCENT)])
    style.configure("Treeview.Heading", background=COLOR_BTN, foreground=COLOR_TEXT, relief="flat")
    style.configure("Vertical.TScrollbar", background=COLOR_BTN, troughcolor=COLOR_BG, arrowcolor=COLOR_TEXT, borderwidth=0)

def get_swizzled_coords(d, pbx):
    tile_idx, in_tile = d // 64, d % 64
    tiles_wide = pbx // 8
    tx, ty = tile_idx % tiles_wide, tile_idx // tiles_wide
    ix = iy = 0
    temp = in_tile
    for i in range(3):
        ix |= (temp & 1) << i
        temp >>= 1
        iy |= (temp & 1) << i
        temp >>= 1
    return tx * 8 + ix, ty * 8 + iy

def decode_dxt5_block(data, offset):
    if offset + 16 > len(data): return np.zeros((4,4,4), dtype=np.uint8)
    a0, a1 = data[offset], data[offset+1]
    ai = int.from_bytes(data[offset+2:offset+8], 'little')
    a = [0]*8
    a[0], a[1] = a0, a1
    if a0 > a1:
        for i in range(6): a[i+2] = ((6-i)*a0 + (i+1)*a1)//7
    else:
        for i in range(4): a[i+2] = ((4-i)*a0 + (i+1)*a1)//5
        a[6], a[7] = 0, 255
    c0, c1 = struct.unpack_from('<HH', data, offset + 8)
    def r565(c): return ((c>>11)&31)*255//31, ((c>>5)&63)*255//63, (c&31)*255//31
    rgb0, rgb1 = r565(c0), r565(c1)
    clrs = [rgb0, rgb1, 
            tuple((2*rgb0[j]+rgb1[j])//3 for j in range(3)),
            tuple((rgb0[j]+2*rgb1[j])//3 for j in range(3))]
    ci = struct.unpack_from('<I', data, offset + 12)[0]
    block = np.zeros((4,4,4), dtype=np.uint8)
    for py in range(4):
        for px in range(4):
            idx = py * 4 + px
            block[py, px, 0:3] = clrs[(ci >> (idx*2)) & 3]
            block[py, px, 3] = a[(ai >> (idx*3)) & 7]
    return block

def encode_dxt5_block(block):
    res = bytearray(16)
    alphas = block[:, :, 3].flatten()
    a0, a1 = np.max(alphas), np.min(alphas)
    res[0], res[1] = a0, a1
    ai = 0
    if a0 != a1:
        a_steps = [a0, a1, (6*a0+a1)//7, (5*a0+2*a1)//7, (4*a0+3*a1)//7, (3*a0+4*a1)//7, (2*a0+5*a1)//7, (a0+6*a1)//7]
        for i, val in enumerate(alphas):
            best_idx = np.argmin([abs(int(val)-int(s)) for s in a_steps])
            ai |= (best_idx & 7) << (i * 3)
    res[2:8] = ai.to_bytes(6, 'little')
    r, g, b = block[0, 0, 0:3]
    c0 = ((int(r)>>3)<<11) | ((int(g)>>2)<<5) | (int(b)>>3)
    struct.pack_into('<HH', res, 8, c0, c0)
    struct.pack_into('<I', res, 12, 0)
    return res

class KsltEditor:
    def __init__(self, parent):
        self.win = tk.Toplevel(parent)
        self.win.title("SonicSlayer - KSLT Archive Editor")
        self.win.geometry("1400x850")
        self.win.configure(bg=COLOR_BG)
        self.set_icon(self.win)
        self.images = []
        self.selected_idx = -1
        self.list_refs = []
        self.preview_ref = None
        
        top = ttk.Frame(self.win)
        top.pack(fill=tk.X, padx=25, pady=20)
        ttk.Button(top, text="Open KSLT", command=self.load_kslt).pack(side=tk.LEFT, padx=5)
        self.save_btn = ttk.Button(top, text="Save KSLT", command=self.save_kslt, state="disabled")
        self.save_btn.pack(side=tk.LEFT, padx=5)

        paned = tk.PanedWindow(self.win, orient=tk.HORIZONTAL, bg=COLOR_BG, bd=0, sashwidth=6)
        paned.pack(fill=tk.BOTH, expand=True)

        left_f = ttk.Frame(paned)
        paned.add(left_f, width=400)
        self.canvas = tk.Canvas(left_f, bg=COLOR_BG, highlightthickness=0)
        self.list_box = ttk.Frame(self.canvas)
        vsb = ttk.Scrollbar(left_f, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas.create_window((0,0), window=self.list_box, anchor="nw")
        self.list_box.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

        self.right_f = ttk.Frame(paned)
        paned.add(self.right_f)
        self.preview_lbl = ttk.Label(self.right_f, text="Select a texture to begin", foreground=COLOR_TEXT_DIM)
        self.preview_lbl.pack(expand=True)
        
        self.bottom = ttk.Frame(self.right_f, style="Surface.TFrame")
        self.bottom.pack(fill=tk.X, padx=20, pady=20)
        self.info_lbl = ttk.Label(self.bottom, text="No Selection", style="Surface.TLabel", font=FONT_B)
        self.info_lbl.pack(side=tk.LEFT, padx=15, pady=15)
        
        self.export_btn = ttk.Button(self.bottom, text="EXPORT PNG", command=self.export_texture, state="disabled")
        self.export_btn.pack(side=tk.RIGHT, padx=5)
        self.import_btn = ttk.Button(self.bottom, text="IMPORT PNG", command=self.import_texture, state="disabled")
        self.import_btn.pack(side=tk.RIGHT, padx=5)

    def set_icon(self, window):
        try:
            window.iconbitmap(resource_path("toolsico.ico"))
        except:
            pass

    def load_kslt(self):
        path = filedialog.askopenfilename(filetypes=[("KSLT Archive", "*.kslt")])
        if not path: return
        with open(path, "rb") as f: data = f.read()
        if data[0:8] != b'TLSK1100': return
        num = struct.unpack_from('<I', data, 8)[0]
        n_off = struct.unpack_from('<I', data, 0x10)[0]
        meta = [struct.unpack_from('<II', data, 0x40 + i*8) for i in range(num)]
        self.images = []
        curr_n = 0x40 + n_off
        for i in range(num):
            n_len, d_off = meta[i]
            name = data[curr_n:curr_n+n_len].decode('utf-8', errors='ignore').strip('\x00')
            curr_n += n_len + 1
            fmt, w, h = struct.unpack_from('<IHH', data, d_off)
            sz = struct.unpack_from('<I', data, d_off + 28)[0]
            self.images.append({"name": name, "fmt": fmt, "w": w, "h": h, "data": data[d_off+0x48:d_off+0x48+sz]})
        self.save_btn.config(state="normal")
        self.render_list()

    def render_list(self):
        for w in self.list_box.winfo_children(): w.destroy()
        self.list_refs.clear()
        for i, img in enumerate(self.images):
            card = tk.Frame(self.list_box, bg=COLOR_SURFACE, padx=10, pady=10, cursor="hand2")
            card.pack(fill=tk.X, padx=10, pady=5)
            try:
                p_img = self.decode_img(img)
                ic = p_img.copy()
                ic.thumbnail((64, 64))
                tk_i = ImageTk.PhotoImage(ic)
                self.list_refs.append(tk_i)
                tk.Label(card, image=tk_i, bg=COLOR_SURFACE).pack(side=tk.LEFT)
            except: pass
            tf = tk.Frame(card, bg=COLOR_SURFACE)
            tf.pack(side=tk.LEFT, padx=10)
            tk.Label(tf, text=img['name'], bg=COLOR_SURFACE, fg=COLOR_TEXT, font=FONT_B).pack(anchor="w")
            tk.Label(tf, text=f"{img['w']}x{img['h']} | {'DXT5' if img['fmt']==6 else 'ARGB'}", bg=COLOR_SURFACE, fg=COLOR_TEXT_DIM, font=FONT_S).pack(anchor="w")
            card.bind("<Button-1>", lambda e, idx=i: self.on_select(idx))
            tf.bind("<Button-1>", lambda e, idx=i: self.on_select(idx))

    def decode_img(self, img):
        fmt, w, h, pix = img['fmt'], img['w'], img['h'], img['data']
        if fmt == 0: return Image.fromarray(np.frombuffer(pix, np.uint8).reshape(h,w,4)[..., [2,1,0,3]], 'RGBA')
        bx, by = (w+3)//4, (h+3)//4
        pbx, pby = ((bx+7)//8)*8, ((by+7)//8)*8
        out = np.zeros((pby*4, pbx*4, 4), dtype=np.uint8)
        for i in range(pbx * pby):
            ax, ay = get_swizzled_coords(i, pbx)
            if i*16+16 <= len(pix): out[ay*4:ay*4+4, ax*4:ax*4+4] = decode_dxt5_block(pix, i*16)
        return Image.fromarray(out[:h, :w], 'RGBA')

    def on_select(self, idx):
        self.selected_idx = idx
        img = self.images[idx]
        self.info_lbl.config(text=f"Selected: {img['name']}")
        self.import_btn.config(state="normal")
        self.export_btn.config(state="normal")
        pi = self.decode_img(img)
        sw, sh = self.right_f.winfo_width()-60, self.right_f.winfo_height()-200
        if sw < 100: sw, sh = 800, 600
        pi.thumbnail((sw, sh), Image.Resampling.NEAREST)
        self.preview_ref = ImageTk.PhotoImage(pi)
        self.preview_lbl.config(image=self.preview_ref, text="")

    def export_texture(self):
        p = filedialog.asksaveasfilename(defaultextension=".png", initialfile=f"{self.images[self.selected_idx]['name']}.png")
        if p: self.decode_img(self.images[self.selected_idx]).save(p)

    def import_texture(self):
        p = filedialog.askopenfilename(filetypes=[("PNG", "*.png")])
        if not p: return
        ni = Image.open(p).convert("RGBA")
        target = self.images[self.selected_idx]
        if ni.size != (target['w'], target['h']):
            if not messagebox.askyesno("SonicSlayer", "Resize image?"): return
            ni = ni.resize((target['w'], target['h']), Image.Resampling.LANCZOS)
        bx, by = (target['w']+3)//4, (target['h']+3)//4
        pbx, pby = ((bx+7)//8)*8, ((by+7)//8)*8
        pad = Image.new("RGBA", (pbx*4, pby*4), (0,0,0,0))
        pad.paste(ni, (0,0))
        arr = np.array(pad)
        nd = bytearray()
        for i in range(pbx * pby):
            ax, ay = get_swizzled_coords(i, pbx)
            nd.extend(encode_dxt5_block(arr[ay*4:ay*4+4, ax*4:ax*4+4]))
        self.images[self.selected_idx]['data'] = bytes(nd)
        self.on_select(self.selected_idx)
        self.render_list()

    def save_kslt(self):
        p = filedialog.asksaveasfilename(defaultextension=".kslt")
        if not p: return
        nb = bytearray()
        for img in self.images: nb.extend(img['name'].encode('utf-8') + b'\x00')
        h_sz = 0x40 + len(self.images)*8
        n_st, d_st = h_sz, (h_sz + len(nb) + 15) & ~15
        final = bytearray(b'TLSK1100' + struct.pack('<I', len(self.images)) + b'\x00'*36)
        struct.pack_into('<II', final, 0x10, n_st-0x40, len(nb))
        px_o = d_st
        for img in self.images:
            final.extend(struct.pack('<II', len(img['name']), px_o))
            px_o += (0x48 + len(img['data']) + 15) & ~15
        final.extend(nb)
        while len(final) < d_st: final.append(0)
        for img in self.images:
            final.extend(struct.pack('<IHH', img['fmt'], img['w'], img['h']) + b'\x00'*20 + struct.pack('<I', len(img['data'])) + b'\x00'*40 + img['data'])
            while len(final)%16 != 0: final.append(0)
        struct.pack_into('<I', final, 12, len(final))
        with open(p, "wb") as f: f.write(final)

class StrPackEditorModern:
    def __init__(self, parent):
        self.win = tk.Toplevel(parent)
        self.win.title("SonicSlayer - STRPACK Editor (DOAX3)")
        self.win.geometry("1300x800")
        self.win.configure(bg=COLOR_BG)
        self.set_icon(self.win)
        
        self.file_buffer = None
        self.file_name = ""
        self.strings = []
        self.search_var = tk.StringVar()
        
        top = ttk.Frame(self.win)
        top.pack(fill=tk.X, padx=15, pady=15)
        ttk.Button(top, text="Open BIN file", command=self.load_file).pack(side=tk.LEFT, padx=5)
        self.save_btn = ttk.Button(top, text="Save Patched File", command=self.save_file, state="disabled")
        self.save_btn.pack(side=tk.LEFT, padx=5)
        search_entry = ttk.Entry(top, textvariable=self.search_var, width=30, font=FONT_M)
        search_entry.pack(side=tk.LEFT, padx=20)
        ttk.Label(top, text="Search:").pack(side=tk.LEFT)
        self.search_var.trace("w", lambda *a: self.refresh_tree())
        
        self.status_label = ttk.Label(top, text="No file loaded", foreground=COLOR_TEXT_DIM)
        self.status_label.pack(side=tk.RIGHT, padx=10)
        
        frame = ttk.Frame(self.win)
        frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)
        
        columns = ("offset", "original", "current", "status")
        self.tree = ttk.Treeview(frame, columns=columns, show="headings")
        self.tree.heading("offset", text="Offset")
        self.tree.heading("original", text="Original Text")
        self.tree.heading("current", text="Patched Translation")
        self.tree.heading("status", text="Status")
        self.tree.column("offset", width=80, anchor="center")
        self.tree.column("original", width=400)
        self.tree.column("current", width=500)
        self.tree.column("status", width=100)
        
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.tree.bind("<Double-1>", self.on_edit)
        
    def set_icon(self, window):
        try:
            window.iconbitmap(resource_path("toolsico.ico"))
        except:
            pass

    def load_file(self):
        path = filedialog.askopenfilename(filetypes=[("STRPACK binary", "*.bin"), ("All files", "*.*")])
        if not path:
            return
        with open(path, "rb") as f:
            self.file_buffer = bytearray(f.read())
        self.file_name = os.path.basename(path)
        self.parse_buffer()
        self.status_label.config(text=f"Loaded: {self.file_name} | {len(self.strings)} strings")
        self.save_btn.config(state="normal")
        self.refresh_tree()
        
    def parse_buffer(self):
        self.strings = []
        buf = self.file_buffer
        i = 0
        while i < len(buf) - 1:
            if buf[i] == 0 and buf[i+1] == 0:
                i += 2
                continue
            start = i
            chars = []
            while i < len(buf) - 1:
                code = buf[i] | (buf[i+1] << 8)
                if code == 0:
                    break
                chars.append(code)
                i += 2
            if chars:
                max_len = len(chars) * 2
                original = self.decode_chars(chars)
                self.strings.append({
                    "offset": start,
                    "max_len": max_len,
                    "original": original,
                    "current": original,
                    "modified": False,
                    "error": None
                })
            i += 2
    
    def decode_chars(self, chars):
        res = ""
        for c in chars:
            if (c < 0x20 and c not in (0x0A, 0x0D, 0x09)) or (0x7F <= c <= 0x9F):
                res += f"<{c:02X}>"
            else:
                res += chr(c)
        return res
    
    def encode_string(self, text):
        res = []
        i = 0
        while i < len(text):
            if text[i] == '<' and i+3 < len(text) and text[i+3] == '>':
                hex_str = text[i+1:i+3]
                try:
                    val = int(hex_str, 16)
                    res.append(val)
                    i += 4
                    continue
                except:
                    pass
            res.append(ord(text[i]))
            i += 1
        return res
    
    def refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        query = self.search_var.get().strip().lower()
        for idx, s in enumerate(self.strings):
            if query and query not in s["original"].lower() and query not in s["current"].lower():
                continue
            status = "Modified" if s["modified"] else ("Error" if s["error"] else "OK")
            tags = ()
            if s["modified"]:
                tags = ("modified",)
            if s["error"]:
                tags = ("error",)
            self.tree.insert("", "end", iid=str(idx), values=(
                f"0x{s['offset']:X}",
                s["original"],
                s["current"],
                status
            ), tags=tags)
        self.tree.tag_configure("modified", background=COLOR_MODIFIED)
        self.tree.tag_configure("error", background=COLOR_ERROR)
    
    def on_edit(self, event):
        item = self.tree.selection()
        if not item:
            return
        item_id = item[0]
        idx = int(item_id)
        s = self.strings[idx]
        new_text = simpledialog.askstring("Edit String", "Edit text:", initialvalue=s["current"])
        if new_text is not None:
            encoded = self.encode_string(new_text)
            byte_len = len(encoded) * 2
            error = None
            if byte_len > s["max_len"]:
                error = f"Too long! {byte_len} / {s['max_len']} bytes"
            s["current"] = new_text
            s["modified"] = (new_text != s["original"])
            s["error"] = error
            self.refresh_tree()
    
    def save_file(self):
        if not self.file_buffer:
            return
        if any(s["error"] for s in self.strings):
            messagebox.showerror("Cannot save", "Some strings exceed their maximum byte limit. Fix errors first.")
            return
        new_buf = bytearray(self.file_buffer)
        for s in self.strings:
            if s["modified"]:
                encoded = self.encode_string(s["current"])
                for i, ch in enumerate(encoded):
                    new_buf[s["offset"] + i*2] = ch & 0xFF
                    new_buf[s["offset"] + i*2 + 1] = (ch >> 8) & 0xFF
                written = len(encoded) * 2
                for i in range(written, s["max_len"]):
                    new_buf[s["offset"] + i] = 0
        out_path = filedialog.asksaveasfilename(defaultextension=".bin", initialfile=f"patched_{self.file_name}")
        if out_path:
            with open(out_path, "wb") as f:
                f.write(new_buf)
            messagebox.showinfo("Success", f"Saved to {out_path}")

class BakesaleTextRepacker:
    def __init__(self, parent):
        self.win = tk.Toplevel(parent)
        self.win.title("SonicSlayer - BakesaleTextRepacker (Rayman 30th)")
        self.win.geometry("900x700")
        self.win.configure(bg=COLOR_BG)
        self.set_icon(self.win)
        
        self.files = []
        self.header_type = tk.StringVar(value="count_only")
        self.magic_bytes = tk.StringVar(value="")
        self.use_null = tk.BooleanVar(value=False)
        
        main = ttk.Frame(self.win)
        main.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        self.drop_frame = tk.Frame(main, bg=COLOR_SURFACE, height=150, relief="ridge", bd=2)
        self.drop_frame.pack(fill=tk.X, pady=10)
        self.drop_frame.pack_propagate(False)
        lbl = tk.Label(self.drop_frame, text="Drag & Drop .txt files here\nor click to select", 
                       bg=COLOR_SURFACE, fg=COLOR_TEXT_DIM, font=FONT_M)
        lbl.pack(expand=True)
        self.drop_frame.bind("<Button-1>", lambda e: self.select_files())
        self.drop_frame.bind("<DragEnter>", self.on_drag_enter)
        self.drop_frame.bind("<DragLeave>", self.on_drag_leave)
        self.drop_frame.bind("<Drop>", self.on_drop)
        
        self.list_frame = ttk.Frame(main)
        self.list_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        self.file_tree = ttk.Treeview(self.list_frame, columns=("name", "code", "lines"), show="headings", height=6)
        self.file_tree.heading("name", text="File Name")
        self.file_tree.heading("code", text="Lang Code")
        self.file_tree.heading("lines", text="Strings")
        self.file_tree.column("name", width=250)
        self.file_tree.column("code", width=100)
        self.file_tree.column("lines", width=100)
        self.file_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll = ttk.Scrollbar(self.list_frame, orient="vertical", command=self.file_tree.yview)
        self.file_tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.settings_frame = ttk.Frame(main)
        self.settings_frame.pack(fill=tk.X, pady=10)
        self.settings_btn = ttk.Button(self.settings_frame, text="▼ Advanced Binary Settings", command=self.toggle_settings)
        self.settings_btn.pack()
        self.advanced_frame = ttk.Frame(main)
        
        self.gen_btn = ttk.Button(main, text="Generate locale.strings", command=self.generate_binary, state="disabled")
        self.gen_btn.pack(pady=15)
        
        self.context_menu = tk.Menu(self.win, tearoff=0, bg=COLOR_SURFACE, fg=COLOR_TEXT)
        self.context_menu.add_command(label="Remove", command=self.remove_selected)
        self.file_tree.bind("<Button-3>", self.show_context_menu)
    
    def set_icon(self, window):
        try:
            window.iconbitmap(resource_path("toolsico.ico"))
        except:
            pass

    def select_files(self):
        paths = filedialog.askopenfilenames(filetypes=[("Text files", "*.txt")])
        if paths:
            self.process_files(paths)
    
    def on_drag_enter(self, e):
        self.drop_frame.config(bg=COLOR_ACCENT)
    
    def on_drag_leave(self, e):
        self.drop_frame.config(bg=COLOR_SURFACE)
    
    def on_drop(self, e):
        self.drop_frame.config(bg=COLOR_SURFACE)
        messagebox.showinfo("Info", "Drag & drop not fully supported.\nPlease use the file dialog.")
        self.select_files()
    
    def process_files(self, paths):
        for path in paths:
            name = os.path.basename(path)
            with open(path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
            if lines and lines[-1] == "":
                lines.pop()
            code = name.replace(".txt", "")
            if "_" in code:
                code = code.split("_")[-1]
            self.files.append({
                "name": name,
                "code": code,
                "lines": lines
            })
        self.refresh_file_list()
        self.gen_btn.config(state="normal" if self.files else "disabled")
    
    def refresh_file_list(self):
        self.file_tree.delete(*self.file_tree.get_children())
        for f in self.files:
            self.file_tree.insert("", "end", values=(f["name"], f["code"], len(f["lines"])))
    
    def remove_selected(self):
        selected = self.file_tree.selection()
        if not selected:
            return
        indices = [self.file_tree.index(item) for item in selected]
        indices.sort(reverse=True)
        for idx in indices:
            del self.files[idx]
        self.refresh_file_list()
        self.gen_btn.config(state="normal" if self.files else "disabled")
    
    def show_context_menu(self, e):
        item = self.file_tree.identify_row(e.y)
        if item:
            self.file_tree.selection_set(item)
            self.context_menu.post(e.x_root, e.y_root)
    
    def toggle_settings(self):
        if self.advanced_frame.winfo_ismapped():
            self.advanced_frame.pack_forget()
            self.settings_btn.config(text="▼ Advanced Binary Settings")
        else:
            self.build_advanced_panel()
            self.advanced_frame.pack(fill=tk.X, pady=10, before=self.gen_btn)
            self.settings_btn.config(text="▲ Advanced Binary Settings")
    
    def build_advanced_panel(self):
        for widget in self.advanced_frame.winfo_children():
            widget.destroy()
        row = 0
        ttk.Label(self.advanced_frame, text="File Header Layout:").grid(row=row, column=0, sticky="w", padx=5, pady=5)
        header_combo = ttk.Combobox(self.advanced_frame, textvariable=self.header_type, values=["count_only", "count_then_array_ptr", "array_ptr_then_count"], state="readonly")
        header_combo.grid(row=row, column=1, sticky="w", padx=5)
        row += 1
        ttk.Label(self.advanced_frame, text="Magic Bytes (hex):").grid(row=row, column=0, sticky="w", padx=5, pady=5)
        magic_entry = ttk.Entry(self.advanced_frame, textvariable=self.magic_bytes, width=30)
        magic_entry.grid(row=row, column=1, sticky="w", padx=5)
        row += 1
        ttk.Checkbutton(self.advanced_frame, text="Append null terminator to strings", variable=self.use_null).grid(row=row, column=0, columnspan=2, sticky="w", padx=5)
    
    def generate_binary(self):
        if not self.files:
            messagebox.showwarning("No files", "Add at least one .txt file.")
            return
        
        magic_str = self.magic_bytes.get().strip()
        magic = bytearray()
        if magic_str:
            for part in magic_str.split():
                try:
                    magic.append(int(part, 16))
                except:
                    pass
        header_type = self.header_type.get()
        use_null = self.use_null.get()
        
        lang_data = []
        for f in self.files:
            code_bytes = f["code"].encode("utf-8")
            if use_null:
                code_bytes += b'\x00'
            strings_data = []
            for line in f["lines"]:
                s_bytes = line.encode("utf-8")
                if use_null:
                    s_bytes += b'\x00'
                strings_data.append(s_bytes)
            lang_data.append({
                "code_bytes": code_bytes,
                "strings_data": strings_data
            })
        
        header_size = len(magic)
        if header_type == "count_only":
            header_size += 4
        else:
            header_size += 8
        
        entries_offset = header_size
        data_offset = entries_offset + len(self.files) * 16
        
        total_size = data_offset
        for ld in lang_data:
            total_size += len(ld["code_bytes"])
            total_size += len(ld["strings_data"]) * 8
            for s in ld["strings_data"]:
                total_size += len(s)
        
        buf = bytearray(total_size)
        buf[:len(magic)] = magic
        
        pos = len(magic)
        if header_type == "count_only":
            struct.pack_into("<I", buf, pos, len(self.files))
        elif header_type == "count_then_array_ptr":
            struct.pack_into("<I", buf, pos, len(self.files))
            struct.pack_into("<I", buf, pos+4, entries_offset - (pos+4))
        elif header_type == "array_ptr_then_count":
            struct.pack_into("<I", buf, pos, entries_offset - pos)
            struct.pack_into("<I", buf, pos+4, len(self.files))
        
        current_data_ptr = data_offset
        for i, ld in enumerate(lang_data):
            entry_pos = entries_offset + i * 16
            code_offset = current_data_ptr - entry_pos
            struct.pack_into("<I", buf, entry_pos, code_offset)
            struct.pack_into("<I", buf, entry_pos+4, len(ld["code_bytes"]))
            buf[current_data_ptr:current_data_ptr+len(ld["code_bytes"])] = ld["code_bytes"]
            current_data_ptr += len(ld["code_bytes"])
            
            strings_offset = current_data_ptr - (entry_pos + 8)
            struct.pack_into("<I", buf, entry_pos+8, strings_offset)
            struct.pack_into("<I", buf, entry_pos+12, len(ld["strings_data"]))
            
            string_header_start = current_data_ptr
            current_data_ptr += len(ld["strings_data"]) * 8
            for j, s_bytes in enumerate(ld["strings_data"]):
                header_pos = string_header_start + j * 8
                offset_val = current_data_ptr - header_pos
                struct.pack_into("<I", buf, header_pos, offset_val)
                struct.pack_into("<I", buf, header_pos+4, len(s_bytes))
                buf[current_data_ptr:current_data_ptr+len(s_bytes)] = s_bytes
                current_data_ptr += len(s_bytes)
        
        out_path = filedialog.asksaveasfilename(defaultextension=".strings", initialfile="locale.strings")
        if out_path:
            with open(out_path, "wb") as f:
                f.write(buf)
            messagebox.showinfo("Success", f"Saved to {out_path}")

class CowabungaTool:
    def __init__(self, parent):
        self.win = tk.Toplevel(parent)
        self.win.title("SonicSlayer - Cowabunga (Digital Eclipse .pie decryptor)")
        self.win.geometry("600x400")
        self.win.configure(bg=COLOR_BG)
        self.set_icon(self.win)
        
        ttk.Label(self.win, text="Cowabunga Decryption Tool", font=FONT_B).pack(pady=20)
        
        frame = ttk.Frame(self.win)
        frame.pack(pady=10)
        
        ttk.Label(frame, text="Input .pie file:").grid(row=0, column=0, sticky="e", padx=5)
        self.input_path = tk.StringVar()
        ttk.Entry(frame, textvariable=self.input_path, width=40).grid(row=0, column=1, padx=5)
        ttk.Button(frame, text="Browse", command=self.browse_input).grid(row=0, column=2)
        
        ttk.Label(frame, text="Output file:").grid(row=1, column=0, sticky="e", padx=5)
        self.output_path = tk.StringVar()
        ttk.Entry(frame, textvariable=self.output_path, width=40).grid(row=1, column=1, padx=5)
        ttk.Button(frame, text="Browse", command=self.browse_output).grid(row=1, column=2)
        
        ttk.Label(frame, text="Key preset:").grid(row=2, column=0, sticky="e", padx=5)
        self.key_preset = tk.StringVar(value="Rayman30th")
        key_combo = ttk.Combobox(frame, textvariable=self.key_preset, values=["Cowabunga", "Atari", "Rayman30th", "MightyMorphin", "YuGiOh", "MortalKombatLC", "Custom"])
        key_combo.grid(row=2, column=1, sticky="w", padx=5)
        
        ttk.Label(frame, text="Custom key (hex):").grid(row=3, column=0, sticky="e", padx=5)
        self.custom_key = tk.StringVar()
        ttk.Entry(frame, textvariable=self.custom_key, width=30).grid(row=3, column=1, sticky="w", padx=5)
        
        ttk.Button(self.win, text="Decrypt / Encrypt", command=self.run_cowabunga).pack(pady=20)
        ttk.Label(self.win, text="Requires cowabunga64.exe embedded or in the same folder", foreground=COLOR_TEXT_DIM).pack()
    
    def set_icon(self, window):
        try:
            window.iconbitmap(resource_path("toolsico.ico"))
        except:
            pass

    def browse_input(self):
        p = filedialog.askopenfilename(filetypes=[("PIE files", "*.pie"), ("All files", "*.*")])
        if p:
            self.input_path.set(p)
            base = os.path.splitext(p)[0]
            self.output_path.set(base + "_decrypted.zip")
    
    def browse_output(self):
        p = filedialog.asksaveasfilename(defaultextension=".zip")
        if p:
            self.output_path.set(p)
    
    def run_cowabunga(self):
        input_file = self.input_path.get().strip()
        output_file = self.output_path.get().strip()
        if not input_file or not output_file:
            messagebox.showerror("Error", "Please select input and output files.")
            return
        
        key_preset = self.key_preset.get()
        exe_path = resource_path("cowabunga64.exe")
        
        args = [exe_path]
        if key_preset == "Custom":
            custom = self.custom_key.get().strip()
            if not custom:
                messagebox.showerror("Error", "Enter custom key in hex (e.g., 0x64DA7B23)")
                return
            args.extend(["-c", custom])
        else:
            key_map = {
                "Cowabunga": "cowabunga",
                "Atari": "atari",
                "Rayman30th": "rayman30th",
                "MightyMorphin": "mightymorphin",
                "YuGiOh": "yugioh",
                "MortalKombatLC": "mortalkombatlc"
            }
            key_arg = key_map.get(key_preset, "rayman30th")
            args.extend(["-k", key_arg])
        
        args.extend([input_file, output_file])
        
        try:
            result = subprocess.run(args, capture_output=True, text=True, check=False)
            if result.returncode == 0:
                messagebox.showinfo("Success", f"Decryption completed.\nOutput: {output_file}")
            else:
                messagebox.showerror("Error", f"Cowabunga failed:\n{result.stderr}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

class BakesaleExtractorTool:
    def __init__(self, parent):
        self.win = tk.Toplevel(parent)
        self.win.title("SonicSlayer - Bakesale Extractor (Rayman 30th)")
        self.win.geometry("600x350")
        self.win.configure(bg=COLOR_BG)
        self.set_icon(self.win)
        
        ttk.Label(self.win, text="Bakesale Extractor", font=FONT_B).pack(pady=20)
        
        frame = ttk.Frame(self.win)
        frame.pack(pady=10)
        
        ttk.Label(frame, text="Input file or directory:").grid(row=0, column=0, sticky="e", padx=5)
        self.input_path = tk.StringVar()
        ttk.Entry(frame, textvariable=self.input_path, width=40).grid(row=0, column=1, padx=5)
        ttk.Button(frame, text="Browse", command=self.browse_input).grid(row=0, column=2)
        
        ttk.Label(frame, text="Output directory (optional):").grid(row=1, column=0, sticky="e", padx=5)
        self.output_dir = tk.StringVar()
        ttk.Entry(frame, textvariable=self.output_dir, width=40).grid(row=1, column=1, padx=5)
        ttk.Button(frame, text="Browse", command=self.browse_output).grid(row=1, column=2)
        
        ttk.Button(self.win, text="Run Extractor", command=self.run_extractor).pack(pady=30)
        ttk.Label(self.win, text="Requires BakesaleExtractor.exe embedded or in the same folder", foreground=COLOR_TEXT_DIM).pack()
    
    def set_icon(self, window):
        try:
            window.iconbitmap(resource_path("toolsico.ico"))
        except:
            pass

    def browse_input(self):
        path = filedialog.askopenfilename(filetypes=[("All files", "*.*")])
        if not path:
            path = filedialog.askdirectory()
        if path:
            self.input_path.set(path)
    
    def browse_output(self):
        path = filedialog.askdirectory()
        if path:
            self.output_dir.set(path)
    
    def run_extractor(self):
        input_path = self.input_path.get().strip()
        if not input_path:
            messagebox.showerror("Error", "Please select input file or directory.")
            return
        
        exe_path = resource_path("BakesaleExtractor.exe")
        args = [exe_path, input_path]
        output_dir = self.output_dir.get().strip()
        if output_dir:
            args.append(output_dir)
        
        try:
            result = subprocess.run(args, capture_output=True, text=True, check=False)
            if result.returncode == 0:
                messagebox.showinfo("Success", "Extraction completed successfully.")
            else:
                messagebox.showerror("Error", f"BakesaleExtractor failed:\n{result.stderr}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

class HoverButton(tk.Button):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.default_bg = self.cget("bg")
        self.default_pady = self.cget("pady") if self.cget("pady") else 0
        self.bind("<Enter>", self.on_enter)
        self.bind("<Leave>", self.on_leave)
    
    def on_enter(self, e):
        self.config(bg=COLOR_BTN_HOVER)
        if self.master.grid_slaves():
            info = self.grid_info()
            if info:
                pady = info.get('pady', (0,0))
                if isinstance(pady, int):
                    pady = (pady, pady)
                self.grid_configure(pady=(pady[0]-2, pady[1]+2))
    
    def on_leave(self, e):
        self.config(bg=self.default_bg)
        if self.master.grid_slaves():
            info = self.grid_info()
            if info:
                pady = info.get('pady', (0,0))
                if isinstance(pady, int):
                    pady = (pady, pady)
                self.grid_configure(pady=(pady[0]+2, pady[1]-2))

class HoverCard(tk.Frame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.default_pady = 10
        self.bind("<Enter>", self.on_enter)
        self.bind("<Leave>", self.on_leave)
    
    def on_enter(self, e):
        info = self.grid_info()
        if info:
            pady = info.get('pady', (10,10))
            if isinstance(pady, int):
                pady = (pady, pady)
            self.grid_configure(pady=(pady[0]-3, pady[1]+3))
    
    def on_leave(self, e):
        info = self.grid_info()
        if info:
            pady = info.get('pady', (10,10))
            if isinstance(pady, int):
                pady = (pady, pady)
            self.grid_configure(pady=(pady[0]+3, pady[1]-3))

class SonicSlayerApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("SonicSlayer Tools [demo-preview v0.0.1]")
        self.root.geometry("494x800")
        self.root.configure(bg=COLOR_BG)
        self.root.resizable(False, False)
        apply_modern_style()
        
        try:
            self.root.iconbitmap(resource_path("toolsico.ico"))
        except:
            pass
        
        self.icons = {}
        self.build_ui()
    
    def build_ui(self):
        try:
            logo_img = Image.open(resource_path("logo.png")).convert("RGBA")
            max_width = 450
            ratio = max_width / logo_img.width
            new_size = (max_width, int(logo_img.height * ratio))
            logo_img = logo_img.resize(new_size, Image.Resampling.LANCZOS)
            self.logo_tk = ImageTk.PhotoImage(logo_img)
            logo_label = ttk.Label(self.root, image=self.logo_tk, background=COLOR_BG)
            logo_label.pack(pady=20)
        except:
            ttk.Label(self.root, text="SONICSLAYER TOOLS", style="Title.TLabel").pack(pady=40)
        
        container = ttk.Frame(self.root)
        container.pack(expand=True, fill=tk.BOTH, padx=20, pady=10)
        
        games = [
            ("DEAD OR ALIVE XTREME 3 FORTUNE", "icon.png", self.open_doa),
            ("RAYMAN 30TH ANNIVERSARY EDITION", "icon2.png", self.open_rayman),
            ("Ultimate Spider-Man", "icon3.png", lambda: messagebox.showinfo("sorry", "Ultimate Spider-Man tools coming soon!")),
            ("Persona 5 Strikers", "icon4.png", lambda: messagebox.showinfo("sorry", "Persona 5 Strikers tools coming soon!"))
        ]
        
        for i, (title, img_file, cmd) in enumerate(games):
            row = i // 2
            col = i % 2
            self.add_card(container, row, col, title, img_file, cmd)
    
    def add_card(self, parent, row, col, title, img_p, cmd):
        card = HoverCard(parent, bg=COLOR_BG)
        card.grid(row=row, column=col, padx=15, pady=10, sticky="n")
        
        try:
            img = Image.open(resource_path(img_p)).convert("RGBA")
            img = img.resize((200, 200), Image.Resampling.LANCZOS)
            tk_i = ImageTk.PhotoImage(img)
            self.icons[title] = tk_i
            btn = HoverButton(card, image=tk_i, bg=COLOR_BG, bd=0, activebackground=COLOR_BG, cursor="hand2", command=cmd)
            btn.pack(pady=(0,10))
        except:
            btn = HoverButton(card, text="ICON", width=20, height=10, bg=COLOR_SURFACE, fg=COLOR_TEXT, command=cmd)
            btn.pack(pady=(0,10))
        
        ttk.Label(card, text=title, font=FONT_B, wraplength=180, justify="center").pack()
    
    def open_doa(self):
        sub = tk.Toplevel(self.root)
        sub.title("SonicSlayer - DOAX3 Fortune")
        sub.geometry("380x280")
        sub.configure(bg=COLOR_BG)
        try:
            sub.iconbitmap(resource_path("toolsico.ico"))
        except:
            pass
        
        main = ttk.Frame(sub)
        main.pack(expand=True, fill=tk.BOTH)
        ttk.Label(main, text="DOAX3 FORTUNE TOOLS", font=FONT_B).pack(pady=30)
        btn1 = HoverButton(main, text="KSLT TEXTURE MODDER", width=35, bg=COLOR_BTN, fg=COLOR_TEXT, command=lambda: KsltEditor(self.root))
        btn1.pack(pady=10)
        btn2 = HoverButton(main, text="STRPACK TEXT MODDER", width=35, bg=COLOR_BTN, fg=COLOR_TEXT, command=lambda: StrPackEditorModern(self.root))
        btn2.pack(pady=10)
    
    def open_rayman(self):
        sub = tk.Toplevel(self.root)
        sub.title("SonicSlayer - Rayman 30th Anniversary Edition")
        sub.geometry("500x450")
        sub.configure(bg=COLOR_BG)
        try:
            sub.iconbitmap(resource_path("toolsico.ico"))
        except:
            pass
        
        main = ttk.Frame(sub)
        main.pack(expand=True, fill=tk.BOTH)
        ttk.Label(main, text="RAYMAN 30TH TOOLS", font=FONT_B).pack(pady=30)
        btn1 = HoverButton(main, text="BakesaleTextRepacker", width=35, bg=COLOR_BTN, fg=COLOR_TEXT, command=lambda: BakesaleTextRepacker(self.root))
        btn1.pack(pady=10)
        btn2 = HoverButton(main, text="Bakesale Extractor (by RayCarrot)", width=35, bg=COLOR_BTN, fg=COLOR_TEXT, command=lambda: BakesaleExtractorTool(self.root))
        btn2.pack(pady=10)
        btn3 = HoverButton(main, text="Cowabunga (by Masquerade64)", width=35, bg=COLOR_BTN, fg=COLOR_TEXT, command=lambda: CowabungaTool(self.root))
        btn3.pack(pady=10)

if __name__ == "__main__":
    app = SonicSlayerApp()
    app.root.mainloop()