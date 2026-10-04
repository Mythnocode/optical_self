"""Original 2D bench drawing geometry, expressed as renderer independent primitives."""
import math
from .teaching_assets import visual_housing, BREADBOARD_LENGTH_MM, BREADBOARD_WIDTH_MM, BREADBOARD_HOLE_PITCH_MM
from .teaching_model import MIRROR_RUNTIME_FOLD_DEG

KIND_COLORS = {
    'laser': '#dc2626', 'isolator': '#4b5563', 'waveplate': '#7c3aed', 'lens': '#2563eb',
    'cylindrical_lens': '#1d4ed8', 'beam_expander': '#0284c7', 'aperture': '#334155',
    'pbs': '#0f766e', 'splitter': '#0891b2', 'beam_sampler': '#64748b', 'grating': '#ca8a04',
    'mirror': '#d97706', 'fiber': '#0f766e', 'ccd': '#7c3aed', 'power_meter': '#475569',
    'wavefront_sensor': '#6366f1', 'oscilloscope': '#1e293b',
}

def color(hex_value, alpha=255, darker=100):
    channels = [int(hex_value[i:i+2], 16) for i in (1, 3, 5)]
    return [round(c * 100 / darker) for c in channels] + [alpha]

def component_primitives(kind, label, length, aperture, scale=8.0, selected=False, hovered=False):
    px_len = max(length * scale * .5, 11.0)
    px_ap = max(aperture * scale * .42, 10.0)
    paint = []
    base = KIND_COLORS.get(kind, '#64748b')
    def shape(name, bounds, fill, stroke=None, width=0, radius=0):
        paint.append({'shape': name, 'bounds': list(bounds), 'fill': fill, 'stroke': stroke, 'width': width, 'radius': radius})
    if selected or hovered:
        accent = '#d97706' if selected else '#2563eb'
        shape('ellipse', (-px_ap-7,-px_ap-7,(px_ap+7)*2,(px_ap+7)*2), color(accent,28), color(accent),1.8)
    if kind != 'oscilloscope':
        shape('ellipse', (-4.2,-4.2,8.4,8.4), color('#8B95A0'),color('#64748b'),.8)
    mount, edge = color('#2A3038'), color('#111827')
    if kind in {'lens','cylindrical_lens','aperture','waveplate','isolator','beam_expander'}:
        shape('ellipse',(-px_ap-3.2,-px_ap-3.2,(px_ap+3.2)*2,(px_ap+3.2)*2),mount,edge,.9)
        shape('ellipse',(-px_ap,-px_ap,px_ap*2,px_ap*2),color(base,220),color(base,darker=150),1.2)
        if kind == 'aperture': shape('ellipse',(-px_ap*.34,-px_ap*.34,px_ap*.68,px_ap*.68),color('#e8edf2'))
        else: shape('ellipse',(-px_ap*.45,-px_ap*.55,px_ap*.7,px_ap*.5),[255,255,255,45])
    elif kind in {'mirror','splitter','beam_sampler','grating','pbs'}:
        shape('rect',(-px_len*.22,-px_ap-3,px_len*.95,(px_ap+3)*2),mount,edge,.9,2)
        shape('rect',(-px_len*.18,-px_ap,px_len*.48,px_ap*2),color(base,230),color(base,darker=140),1.1,1.5)
    elif kind == 'laser':
        shape('rect',(-px_len*.12,-px_ap*.85,px_len*.95,px_ap*1.7),mount,edge,.9,2)
        shape('rect',(-px_len,-px_ap*.5,px_len*1.55,px_ap),color(base),color(base,darker=140),1,3)
    elif kind == 'fiber':
        shape('rect',(-px_ap-2,-px_ap-2,(px_ap+2)*2,(px_ap+2)*2),mount,edge,.9,3)
        shape('rect',(-px_ap,-px_ap*.7,px_ap*2,px_ap*1.4),color(base,220),color(base,darker=140),1,3)
    elif kind == 'ccd':
        shape('rect',(-px_ap-2,-px_ap*.85,px_ap*2+4,px_ap*1.7),mount,edge,.9,2)
        shape('rect',(-px_ap,-px_ap*.7,px_ap*2,px_ap*1.4),color(base,220),color(base,darker=140),1)
    else:
        shape('rect',(-px_len-2,-px_ap*.85,px_len*2+4,px_ap*1.7),mount,edge,.9,2)
        shape('rect',(-px_len,-px_ap*.7,px_len*2,px_ap*1.4),color(base,210),color(base,darker=140),1,3)
    paint.append({'shape':'text','bounds':[-48,px_ap+4,96,14],'text':label,'fill':color('#0f172a'),'font_size':8,'alignment':'center'})
    return paint

def canvas_presentation(snapshot):
    scale = 8.0
    components = []
    bounds = []
    for item in snapshot.components:
        housing = visual_housing(item.kind,item.params)
        length, aperture = max(housing.length_mm,4.0), max(housing.aperture_mm,6.0)
        x,y = item.pose.x_mm*scale,-item.pose.y_mm*scale
        yaw = -(item.pose.yaw_deg+(MIRROR_RUNTIME_FOLD_DEG if item.kind=='mirror' else 0))
        half = max(aperture,length)*scale*.8+22
        rotated_half = half*(abs(math.cos(math.radians(yaw)))+abs(math.sin(math.radians(yaw))))
        bounds.append((x-rotated_half,y-rotated_half,x+rotated_half,y+rotated_half))
        components.append({'component_id':item.component_id,'x':x,'y':y,'rotation':yaw,'length':length,'aperture':aperture,
                           'primitives':component_primitives(item.kind,item.label,length,aperture,scale),
                           'selected_primitives':component_primitives(item.kind,item.label,length,aperture,scale,selected=True),
                           'hover_primitives':component_primitives(item.kind,item.label,length,aperture,scale,hovered=True)})
    if bounds:
        left,top=min(b[0] for b in bounds)-48,min(b[1] for b in bounds)-36
        right,bottom=max(b[2] for b in bounds)+48,max(b[3] for b in bounds)+36
        fit=[left,top,right-left,bottom-top]
    else:fit=[-20,-1300,3640,2600]
    return {'scale':scale,'scene_bounds':[-40,-1320,3680,2640],'fit_bounds':fit,'components':components,
            'board':[0,-.5*BREADBOARD_WIDTH_MM*scale,BREADBOARD_LENGTH_MM*scale,BREADBOARD_WIDTH_MM*scale],
            'holes':[[12.5*scale+ix*BREADBOARD_HOLE_PITCH_MM*scale,-.5*BREADBOARD_WIDTH_MM*scale+12.5*scale+iy*BREADBOARD_HOLE_PITCH_MM*scale]
                     for ix in range(int(BREADBOARD_LENGTH_MM/BREADBOARD_HOLE_PITCH_MM)) for iy in range(int(BREADBOARD_WIDTH_MM/BREADBOARD_HOLE_PITCH_MM))]}
