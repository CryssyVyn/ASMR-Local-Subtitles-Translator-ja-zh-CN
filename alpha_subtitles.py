"""Antialiased GDI+ subtitle paths on a per-pixel-alpha Windows layered window.

No color-key removal or ClearType background pixels are used. The backing DIB
is premultiplied BGRA, as required by UpdateLayeredWindow/AC_SRC_ALPHA.
"""
import ctypes as C
from ctypes import wintypes as W
from contextlib import contextmanager

import numpy as np
from scipy.ndimage import gaussian_filter


class RectF(C.Structure):
    _fields_=[('x',C.c_float),('y',C.c_float),('width',C.c_float),('height',C.c_float)]


class StartupInput(C.Structure):
    _fields_=[('version',W.UINT),('callback',C.c_void_p),('no_thread',W.BOOL),('no_codecs',W.BOOL)]


class BitmapInfo(C.Structure):
    _fields_=[('size',W.DWORD),('width',W.LONG),('height',W.LONG),('planes',W.WORD),
              ('bits',W.WORD),('compression',W.DWORD),('image_size',W.DWORD),
              ('xppm',W.LONG),('yppm',W.LONG),('used',W.DWORD),('important',W.DWORD)]


class Blend(C.Structure):
    _fields_=[('operation',W.BYTE),('flags',W.BYTE),('alpha',W.BYTE),('format',W.BYTE)]


def bind(dll,name,result,*arguments):
    function=getattr(dll,name)
    function.restype=result
    function.argtypes=list(arguments)
    return function


user=C.WinDLL('user32',use_last_error=True)
gdi=C.WinDLL('gdi32',use_last_error=True)
bind(user,'GetDC',W.HDC,W.HWND)
bind(user,'ReleaseDC',C.c_int,W.HWND,W.HDC)
bind(user,'GetAncestor',W.HWND,W.HWND,W.UINT)
bind(user,'GetWindowLongW',W.LONG,W.HWND,C.c_int)
bind(user,'SetWindowLongW',W.LONG,W.HWND,C.c_int,W.LONG)
bind(user,'UpdateLayeredWindow',W.BOOL,W.HWND,W.HDC,C.POINTER(W.POINT),C.POINTER(W.SIZE),
     W.HDC,C.POINTER(W.POINT),W.DWORD,C.POINTER(Blend),W.DWORD)
bind(gdi,'CreateCompatibleDC',W.HDC,W.HDC)
bind(gdi,'CreateDIBSection',W.HBITMAP,W.HDC,C.POINTER(BitmapInfo),W.UINT,
     C.POINTER(C.c_void_p),W.HANDLE,W.DWORD)
bind(gdi,'SelectObject',W.HANDLE,W.HDC,W.HANDLE)
bind(gdi,'DeleteObject',W.BOOL,W.HANDLE)
bind(gdi,'DeleteDC',W.BOOL,W.HDC)


class Surface:
    def __init__(self,width,height):
        self.width=width;self.height=height
        self.dc=None;self.bitmap=None;self.old=None
        screen=user.GetDC(None)
        try:
            self.dc=gdi.CreateCompatibleDC(screen)
            info=BitmapInfo(C.sizeof(BitmapInfo),width,-height,1,32,0,width*height*4,0,0,0,0)
            bits=C.c_void_p()
            self.bitmap=gdi.CreateDIBSection(screen,C.byref(info),0,C.byref(bits),None,0)
            if not self.dc or not self.bitmap:
                raise C.WinError(C.get_last_error())
            self.old=gdi.SelectObject(self.dc,self.bitmap)
            self.bits=bits
            self.pixels=np.ctypeslib.as_array((W.BYTE*(width*height*4)).from_address(bits.value)).reshape(height,width,4)
        except Exception:
            self.close()
            raise
        finally:
            user.ReleaseDC(None,screen)

    def close(self):
        if self.old and self.dc:gdi.SelectObject(self.dc,self.old)
        if self.bitmap:gdi.DeleteObject(self.bitmap)
        if self.dc:gdi.DeleteDC(self.dc)
        self.dc=None;self.bitmap=None;self.old=None


class AlphaSubtitles:
    def __init__(self):
        self.dll=C.WinDLL('gdiplus')
        self.surface=None
        self.families={}
        self.last_frame={}
        self.closed=False
        pointer=C.c_void_p;out=C.POINTER(pointer);integer=C.c_int;real=C.c_float
        signatures={
            'GdiplusStartup':(C.POINTER(C.c_size_t),C.POINTER(StartupInput),pointer),
            'GdipCreateBitmapFromScan0':(integer,integer,integer,integer,pointer,out),
            'GdipGetImageGraphicsContext':(pointer,out),
            'GdipSetSmoothingMode':(pointer,integer),
            'GdipSetPixelOffsetMode':(pointer,integer),
            'GdipFlush':(pointer,integer),
            'GdipDeleteGraphics':(pointer,), 'GdipDisposeImage':(pointer,),
            'GdipCreateFontFamilyFromName':(W.LPCWSTR,pointer,out),
            'GdipGetGenericFontFamilySansSerif':(out,), 'GdipDeleteFontFamily':(pointer,),
            'GdipCreateFont':(pointer,real,integer,integer,out), 'GdipDeleteFont':(pointer,),
            'GdipStringFormatGetGenericDefault':(out,),
            'GdipSetStringFormatAlign':(pointer,integer),
            'GdipDeleteStringFormat':(pointer,),
            'GdipMeasureString':(pointer,W.LPCWSTR,integer,pointer,C.POINTER(RectF),pointer,
                                 C.POINTER(RectF),C.POINTER(integer),C.POINTER(integer)),
            'GdipCreatePath':(integer,out), 'GdipDeletePath':(pointer,),
            'GdipAddPathString':(pointer,W.LPCWSTR,integer,pointer,integer,real,C.POINTER(RectF),pointer),
            'GdipCreateSolidFill':(W.DWORD,out), 'GdipDeleteBrush':(pointer,),
            'GdipFillPath':(pointer,pointer,pointer),
            'GdipCreatePen1':(W.DWORD,real,integer,out), 'GdipDeletePen':(pointer,),
            'GdipSetPenLineJoin':(pointer,integer), 'GdipDrawPath':(pointer,pointer,pointer),
        }
        for name,args in signatures.items():bind(self.dll,name,integer,*args)
        bind(self.dll,'GdiplusShutdown',None,C.c_size_t)
        self.token=C.c_size_t()
        self.check(self.dll.GdiplusStartup(C.byref(self.token),C.byref(StartupInput(1,None,False,False)),None))

    @staticmethod
    def check(status):
        if status:raise RuntimeError(f'字幕文字绘制失败（GDI+ {status}）')

    def call(self,name,*arguments):
        self.check(getattr(self.dll,name)(*arguments))

    def family(self,name):
        if name not in self.families:
            value=C.c_void_p()
            status=self.dll.GdipCreateFontFamilyFromName(name,None,C.byref(value))
            if status:self.call('GdipGetGenericFontFamilySansSerif',C.byref(value))
            self.families[name]=value
        return self.families[name]

    @contextmanager
    def graphics(self):
        image=C.c_void_p();graphics=C.c_void_p()
        try:
            surface=self.surface
            self.call('GdipCreateBitmapFromScan0',surface.width,surface.height,surface.width*4,
                      0x000E200B,surface.bits,C.byref(image))
            self.call('GdipGetImageGraphicsContext',image,C.byref(graphics))
            self.call('GdipSetSmoothingMode',graphics,4)
            self.call('GdipSetPixelOffsetMode',graphics,4)
            yield graphics
            self.call('GdipFlush',graphics,1)
        finally:
            if graphics.value:self.dll.GdipDeleteGraphics(graphics)
            if image.value:self.dll.GdipDisposeImage(image)

    @staticmethod
    def argb(color,alpha=255):
        return (alpha<<24)|int(color.lstrip('#'),16)

    def fill(self,graphics,path,color):
        brush=C.c_void_p()
        try:
            self.call('GdipCreateSolidFill',color,C.byref(brush))
            self.call('GdipFillPath',graphics,brush,path)
        finally:
            if brush.value:self.dll.GdipDeleteBrush(brush)

    def measure(self,graphics,text,family,size,style,width,formatting):
        font=C.c_void_p()
        try:
            self.call('GdipCreateFont',family,size,style,2,C.byref(font))
            bounds=RectF();layout=RectF(0,0,width,10000)
            self.call('GdipMeasureString',graphics,text,-1,font,C.byref(layout),formatting,C.byref(bounds),None,None)
            return bounds.height
        finally:
            if font.value:self.dll.GdipDeleteFont(font)

    def render(self,window,zh,ja,options):
        if self.closed:return
        width=window.winfo_width();height=window.winfo_height()
        if width<2 or height<2:return
        if self.surface is None or (self.surface.width,self.surface.height)!=(width,height):
            if self.surface:self.surface.close()
            self.surface=Surface(width,height)
        pixels=self.surface.pixels
        pixels[:]=0
        paths=[];formatting=C.c_void_p()
        try:
            self.call('GdipStringFormatGetGenericDefault',C.byref(formatting))
            self.call('GdipSetStringFormatAlign',formatting,1)
            scale=float(window.winfo_fpixels('1p'))
            style=1 if options['overlay_font_weight']=='bold' else 0
            rows=[]
            for text,name,size,color in ((zh,'Microsoft YaHei UI',options['font_size'],options['overlay_zh_color']),
                                         (ja,'Yu Gothic UI',options['ja_font_size'],options['overlay_ja_color'])):
                if text:rows.append([text,self.family(name),size*scale,color])
            with self.graphics() as graphics:
                heights=[self.measure(graphics,text,family,size,style,width-32,formatting)
                         for text,family,size,color in rows]
                total=sum(heights)+6*max(0,len(rows)-1)
                if total>height-24:
                    factor=max(.5,(height-24)/total)
                    for row in rows:row[2]*=factor
                    heights=[self.measure(graphics,text,family,size,style,width-32,formatting)
                             for text,family,size,color in rows]
                    total=sum(heights)+6*max(0,len(rows)-1)
                y=max(12,(height-total)/2)
                for (text,family,size,color),row_height in zip(rows,heights):
                    path=C.c_void_p()
                    self.call('GdipCreatePath',0,C.byref(path))
                    paths.append((path,color))
                    layout=RectF(16,y,width-32,row_height+4)
                    self.call('GdipAddPathString',path,text,-1,family,style,size,C.byref(layout),formatting)
                    if options['overlay_shadow']:self.fill(graphics,path,0xFFFFFFFF)
                    y+=row_height+6
            if options['overlay_shadow'] and rows:
                blurred=gaussian_filter(pixels[:,:,3].astype(np.float32),sigma=1.5)
                alpha=np.zeros_like(pixels[:,:,3])
                alpha[2:,1:]=(blurred[:-2,:-1]*.32).astype(np.uint8)
            else:
                alpha=np.zeros_like(pixels[:,:,3])
            pixels[:]=0
            if options['overlay_transparent_bg']:
                pixels[:,:,3]=alpha  # Black shadow; premultiplied RGB remains zero.
            else:
                for channel,value in enumerate((0x2b,0x21,0x17)):
                    pixels[:,:,channel]=(value*(1-alpha.astype(np.float32)/255)).astype(np.uint8)
                pixels[:,:,3]=255
            with self.graphics() as graphics:
                for path,color in paths:
                    if options['overlay_outline_width']:
                        pen=C.c_void_p()
                        try:
                            self.call('GdipCreatePen1',0x80303030,float(options['overlay_outline_width']),2,C.byref(pen))
                            self.call('GdipSetPenLineJoin',pen,2)
                            self.call('GdipDrawPath',graphics,pen,path)
                        finally:
                            if pen.value:self.dll.GdipDeletePen(pen)
                    self.fill(graphics,path,self.argb(color))
            handle=user.GetAncestor(window.winfo_id(),2)
            extended=user.GetWindowLongW(handle,-20)
            if not extended&0x80000:user.SetWindowLongW(handle,-20,extended|0x80000)
            size=W.SIZE(width,height);origin=W.POINT(0,0);blend=Blend(0,0,255,1)
            success=user.UpdateLayeredWindow(handle,None,None,C.byref(size),self.surface.dc,
                                            C.byref(origin),0,C.byref(blend),2)
            if not success:
                # Tk can reset layered-window attributes when changing WM options.
                extended=user.GetWindowLongW(handle,-20)
                user.SetWindowLongW(handle,-20,extended&~0x80000)
                user.SetWindowLongW(handle,-20,extended|0x80000)
                if not user.UpdateLayeredWindow(handle,None,None,C.byref(size),self.surface.dc,
                                                C.byref(origin),0,C.byref(blend),2):
                    raise C.WinError(C.get_last_error())
            self.last_frame={'zh':zh,'ja':ja,'width':width,'height':height,'options':dict(options)}
        finally:
            for path,color in paths:self.dll.GdipDeletePath(path)
            if formatting.value:self.dll.GdipDeleteStringFormat(formatting)

    def close(self):
        if self.closed:return
        self.closed=True
        if self.surface:self.surface.close()
        for family in self.families.values():self.dll.GdipDeleteFontFamily(family)
        self.dll.GdiplusShutdown(self.token)
