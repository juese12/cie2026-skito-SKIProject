"""Read exact VCD frames emitted by the read-only GEMV observer."""
import gzip
from pathlib import Path

REQUIRED={'clock','enable0','enable1','vs1','vs2','sum','out_valid','out_data','out_op',
    'out_tag_flag','out_tag_index','out_vl','out_sew','out_illegal','in_tag_flag','in_tag_index','in_sew'}|{f'p{i}' for i in range(8)}
def read_wave(path):
    path=Path(path);opener=gzip.open if path.suffix=='.gz' else open
    codes={};widths={};current={};frames=[];time=None
    def save():
        if time is None:return
        if not REQUIRED<=set(current):raise ValueError('missing actual VCD values')
        if current['clock']!=(1 if time%2==0 else 0):raise ValueError('clock/phase mismatch')
        frames.append(dict(time=time,cycle=time//2,phase=time%2,**current))
    with opener(path,'rt',encoding='ascii') as f:
        for raw in f:
            p=raw.split()
            if p and p[0]=='$var':codes[p[3]]=p[4];widths[p[4]]=int(p[2])
            if p and p[0]=='$enddefinitions':break
        if not REQUIRED<=set(widths):raise ValueError('missing VCD declarations')
        for raw in f:
            line=raw.strip()
            if not line:continue
            if line.startswith('#'):
                save();new=int(line[1:])
                if time is not None and new<=time:raise ValueError('non-monotonic waveform')
                time=new
            elif line.startswith('b'):
                bits,code=line[1:].split()
                if code in codes:
                    if any(b not in '01' for b in bits):raise ValueError('unknown sampled signal')
                    name=codes[code];v=int(bits,2)
                    if v>=1<<widths[name]:raise ValueError('signal outside declared width')
                    current[name]=v
            elif line[0] in '01' and line[1:] in codes:current[codes[line[1:]]]=int(line[0])
    save()
    if not frames:raise ValueError('empty VCD')
    return frames,widths

def signed(v,bits):return v-(1<<bits) if v&(1<<(bits-1)) else v
def lanes(v):return [signed((v>>(8*i))&255,8) for i in range(8)]
