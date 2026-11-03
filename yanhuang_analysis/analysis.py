#!/usr/bin/env python3
"""沿黄九市评价：完整重算、结果导出、图表及报告。详见README中的口径说明。"""
from pathlib import Path
import os, argparse, json, hashlib
os.environ.setdefault('MPLCONFIGDIR', '/tmp/yanhuang-mpl')
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import rankdata, spearmanr
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from docx import Document
from docx.shared import Inches

COLS=['单位GDP能耗','绿化覆盖率','颗粒物排放量','人均GDP','第三产业占GDP的比重（%）','专利申请授权数','城镇居民人均可支配收入','每千人医疗机构床位数（床/每千人）','每万人公共图书馆藏书量','A级旅游景区数量','旅游人均总消费']
SYSTEMS={'经济发展':[3,6],'创新与产业升级':[4,5,9],'绿色生态发展':[0,1,2],'民生共享发展':[7,8,10]}
GROUPS={'鲁中引领区':['济南','泰安','淄博'],'鲁北生态转型区':['东营','滨州','德州'],'鲁西及鲁西南协同发展区':['菏泽','济宁','聊城']}
CITY_GROUP={c:g for g,cs in GROUPS.items() for c in cs}
YEARS=list(range(2013,2024))

def load_data(path):
    df=pd.read_excel(path)
    df.columns=df.columns.astype(str).str.strip()
    required=['city','year']+COLS
    if not set(required)<=set(df): raise ValueError('缺少列：'+str(set(required)-set(df)))
    df=df[required].copy(); df['city']=df.city.astype(str).str.strip().str.removesuffix('市')
    for c in ['year']+COLS: df[c]=pd.to_numeric(df[c],errors='raise')
    if df.isna().any().any() or not np.isfinite(df[COLS+['year']].values).all(): raise ValueError('存在空值或无穷值，请先核实')
    if df.duplicated(['city','year']).any(): raise ValueError('城市年份重复')
    expected={(c,y) for c in CITY_GROUP for y in YEARS}
    if set(zip(df.city,df.year))!=expected: raise ValueError('必须是指定九市2013—2023年完整99条面板')
    if (df[COLS]<0).any().any(): raise ValueError('出现负值，需核实单位或统计口径')
    if not df['绿化覆盖率'].between(0,100).all() or not df[COLS[4]].between(0,100).all(): raise ValueError('百分比超出0—100')
    df=df.sort_values(['year','city']).reset_index(drop=True); df['区域']=df.city.map(CITY_GROUP)
    return df

def normalize(x):
    lo=x.min(axis=0); hi=x.max(axis=0); span=hi-lo
    z=np.divide(x-lo,span,out=np.zeros_like(x,dtype=float),where=span>0)
    for j in [0,2]: z[:,j]=np.where(span[j]>0,1-z[:,j],0)
    return z,lo,hi

def weights(z):
    n,m=z.shape
    sums=z.sum(axis=0)
    p=np.divide(z,sums,out=np.zeros_like(z),where=sums>0)
    lp=np.zeros_like(p); np.log(p,out=lp,where=p>0)
    d=1+(p*lp).sum(axis=0)/np.log(n); active=np.ptp(z,axis=0)>0; d[~active]=0
    if d.sum()<=0: raise ValueError('所有指标恒定，无法赋权')
    ent=d/d.sum()
    corr=np.eye(m); ix=np.where(active)[0]
    corr[np.ix_(ix,ix)]=np.atleast_2d(np.corrcoef(z[:,ix],rowvar=False))
    # 恒定指标既无权重，也不产生与其他指标的冲突信息。
    conflict=(1-corr[:,ix]).sum(axis=1)
    info=z.std(axis=0,ddof=0)*conflict; info[~active]=0
    if info.sum()<=1e-15: raise ValueError('CRITIC信息量为零')
    critic=info/info.sum(); W=np.vstack([ent,critic]); A=W@W.T; b=np.diag(A)
    alpha=np.linalg.lstsq(A,b,rcond=None)[0]; method='经典博弈均衡线性方程 Aα=diag(A)，系数归一化'
    if (alpha < -1e-10).any() or alpha.sum()<=0:
        # 对均衡方程残差作单纯形约束；仅退化情形启用，必须在报告中披露。
        fit=minimize(lambda a: np.sum((A@a-b)**2),[.5,.5],bounds=[(0,1)]*2,
                     constraints={'type':'eq','fun':lambda a:a.sum()-1},method='SLSQP',options={'ftol':1e-14})
        if not fit.success: raise ValueError(fit.message)
        alpha=fit.x; method='均衡方程出现负系数，改用单纯形约束最小残差组合（非经典无约束均衡）'
    else: alpha=np.maximum(alpha,0); alpha/=alpha.sum()
    return ent,critic,alpha@W,alpha,method

def topsis(z,w):
    w=np.asarray(w); w=w/w.sum(); v=z*w
    pos=v.max(axis=0); neg=v.min(axis=0)
    dp=np.linalg.norm(v-pos,axis=1); dn=np.linalg.norm(v-neg,axis=1)
    return np.divide(dn,dp+dn,out=np.full(len(z),.5),where=dp+dn>0)

def dagum(values,labels):
    x=np.asarray(values,float); labels=np.asarray(labels); n=len(x); mu=x.mean()
    if mu<=0: raise ValueError('Dagum要求正均值')
    denom=2*n*n*mu; total=np.abs(x[:,None]-x).sum()/denom
    within=between=trans=0.; detail={}
    gs=list(dict.fromkeys(labels))
    for i,g in enumerate(gs):
        a=x[labels==g]
        gw=np.abs(a[:,None]-a).sum()/denom; within+=gw
        detail['组内基尼_'+g]=np.abs(a[:,None]-a).sum()/(2*len(a)**2*a.mean()) if a.mean()>0 else 0
        for h in gs[:i]:
            b=x[labels==h]; dif=a[:,None]-b
            # 有序组对总绝对差贡献与均值差对应的净贡献；余项为分布交叉的超变密度。
            pair=np.abs(dif).sum()/(n*n*mu)
            net=abs(dif.sum())/(n*n*mu)
            between+=net; trans+=pair-net
            detail['组间基尼_'+g+'__'+h]=np.abs(dif).mean()/(a.mean()+b.mean())
    res={'总体基尼':total,'组内贡献':within,'组间净贡献':between,'超变密度贡献':trans,
         '变异系数':x.std(ddof=0)/mu,**detail}
    for k in ['组内贡献','组间净贡献','超变密度贡献']: res[k+'率']=res[k]/total if total>0 else 0
    assert np.isclose(total,within+between+trans,atol=1e-12)
    return res

def silverman(x):
    x=np.asarray(x); sd=x.std(ddof=1); iqr=np.subtract(*np.percentile(x,[75,25]))/1.34
    scale=min(sd,iqr) if iqr>0 else sd
    return max(.9*scale*len(x)**(-.2),1e-6)

def kde_reflected(x,grid,h):
    # [0,1]支持域，反射边界修正；不把连续年度池化为独立样本。
    x=np.asarray(x)
    kernels=[np.exp(-.5*((grid[:,None]-centers)/h)**2).sum(axis=1) for centers in [x,-x,2-x]]
    return sum(kernels)/(len(x)*h*np.sqrt(2*np.pi))

def evaluate(df):
    z,lo,hi=normalize(df[COLS].to_numpy(float)); ent,cri,w,a,method=weights(z)
    score=df[['city','year','区域']].copy(); score['综合指数']=topsis(z,w)
    for name,ix in SYSTEMS.items(): score[name]=topsis(z[:,ix],w[ix])
    score['年度排名']=score.groupby('year')['综合指数'].rank(ascending=False,method='min').astype(int)
    return z,lo,hi,ent,cri,w,a,method,score

def audit_data(df):
    rows=[]
    def add(city,year,col,value,reason): rows.append({'city':city,'year':year,'指标':col,'原始值':value,'核查事项':reason})
    for _,r in df.iterrows():
        if r['city']=='济南' and r['year']==2015: add(r.city,r.year,COLS[10],r[COLS[10]],'11.9与相邻年份0.96和1.34差异明显；不能自动认定为1.19')
        if r['city']=='德州' and r['year']==2020: add(r.city,r.year,COLS[10],r[COLS[10]],'零值可能是真实值或缺失编码，需回查')
    for city,g in df.groupby('city'):
        g=g.sort_values('year')
        if g.loc[g.year==2023,COLS[2]].iloc[0]==g.loc[g.year==2022,COLS[2]].iloc[0]:
            add(city,2023,COLS[2],g.loc[g.year==2023,COLS[2]].iloc[0],'与2022完全相同；九市均如此，需核查是否沿用上年值')
        for col in [COLS[3],COLS[4],COLS[6]]:
            change=g[col].pct_change()
            for idx in change.index[change.abs()>.2]:
                r=g.loc[idx]; add(city,int(r.year),col,r[col],f'同比{change.loc[idx]:+.1%}；可能涉及统计口径/区划/基数调整，不能视为同口径增长')
    return pd.DataFrame(rows)

def df_table(df,ndigits=4):
    def fmt(v): return f'{v:.{ndigits}f}' if isinstance(v,(float,np.floating)) else str(v)
    return '\n'.join(['| '+' | '.join(map(str,df.columns))+' |','| '+' | '.join(['---']*len(df.columns))+' |']+['| '+' | '.join(fmt(v) for v in row)+' |' for row in df.itertuples(index=False,name=None)])

def main():
    root=Path(__file__).resolve().parent
    ap=argparse.ArgumentParser(); ap.add_argument('--input',type=Path,default=root/'data/input.xlsx'); ap.add_argument('--output',type=Path,default=root/'output'); args=ap.parse_args()
    out=args.output; out.mkdir(parents=True,exist_ok=True)
    df=load_data(args.input); z,lo,hi,ent,cri,w,a,method,score=evaluate(df)
    wt=pd.DataFrame({'指标':COLS,'子系统':[next(s for s,ix in SYSTEMS.items() if j in ix) for j in range(11)],'方向':['负向' if j in [0,2] else '正向' for j in range(11)],'最小值':lo,'最大值':hi,'熵权':ent,'CRITIC权重':cri,'组合权重':w})
    audit=audit_data(df)
    norm=pd.concat([df[['city','year','区域']],pd.DataFrame(z,columns=COLS)],axis=1)
    ob=(1-z)*w; denom=ob.sum(axis=1)
    ob=np.divide(ob,denom[:,None],out=np.zeros_like(ob),where=denom[:,None]>0)*100
    obstacle=pd.concat([df[['city','year','区域']],pd.DataFrame(ob,columns=COLS)],axis=1)
    sysob=obstacle[['city','year','区域']].copy()
    for name,ix in SYSTEMS.items(): sysob[name]=ob[:,ix].sum(axis=1)
    obs_year=obstacle.groupby('year')[COLS].mean().reset_index()
    obs_region=obstacle.groupby(['year','区域'])[COLS].mean().reset_index()
    yearly=score.groupby('year')[['综合指数']+list(SYSTEMS)].mean().reset_index()
    regional=score.groupby(['year','区域'])[['综合指数']+list(SYSTEMS)].mean().reset_index()
    ds=[]
    for field in ['综合指数']+list(SYSTEMS):
        for year,g in score.groupby('year'): ds.append({'year':year,'评价对象':field,**dagum(g[field],g['区域'])})
    dag=pd.DataFrame(ds); dg=dag[dag['评价对象']=='综合指数'].copy()
    # 每个情景重新计算标准化、权重和理想解；情景是稳健性检验，不是确认的数据修正。
    scenario_frames=[]; scenario_summary=[]
    cases=['原始数据','济南2015旅游插值','德州2020旅游插值','两处旅游联合插值','剔除旅游指标','旅游全样本1%-99%缩尾']
    for case in cases:
        d=df.copy()
        if case in ['济南2015旅游插值','两处旅游联合插值']:
            d.loc[(d.city=='济南')&(d.year==2015),COLS[10]]=d.loc[(d.city=='济南')&d.year.isin([2014,2016]),COLS[10]].mean()
        if case in ['德州2020旅游插值','两处旅游联合插值']:
            d.loc[(d.city=='德州')&(d.year==2020),COLS[10]]=d.loc[(d.city=='德州')&d.year.isin([2019,2021]),COLS[10]].mean()
        if case=='旅游全样本1%-99%缩尾':
            low,high=d[COLS[10]].quantile([.01,.99]); d[COLS[10]]=d[COLS[10]].clip(low,high)
        zs,*_=normalize(d[COLS].to_numpy(float))
        if case=='剔除旅游指标': zs[:,10]=0
        e,c,ws,aa,mm=weights(zs); sc=topsis(zs,ws)
        sf=d[['city','year','区域']].copy(); sf['综合指数']=sc; sf['情景']=case; sf['年度排名']=sf.groupby('year')['综合指数'].rank(ascending=False,method='min').astype(int)
        scenario_frames.append(sf)
        first=sf[sf.year==2013]; last=sf[sf.year==2023]
        rank_base=score[score.year==2023].sort_values('city')['年度排名'].values
        rank_new=last.sort_values('city')['年度排名'].values
        scenario_summary.append({'情景':case,'旅游组合权重':ws[10],'2013均值':first['综合指数'].mean(),'2023均值':last['综合指数'].mean(),'2013基尼':dagum(first['综合指数'],first['区域'])['总体基尼'],'2023基尼':dagum(last['综合指数'],last['区域'])['总体基尼'],'2023排名Spearman':spearmanr(rank_base,rank_new).statistic,'2023最大名次变化':np.max(np.abs(rank_new-rank_base))})
    sens=pd.DataFrame(scenario_summary); all_sens=pd.concat(scenario_frames,ignore_index=True)
    tables={'清洗面板':df,'数据核查清单':audit,'标准化值':norm,'指标权重':wt,'城市年度得分':score,'综合指数城市年份表':score.pivot(index='city',columns='year',values='综合指数').reset_index(),'年度排名城市年份表':score.pivot(index='city',columns='year',values='年度排名').reset_index(),'年度均值':yearly,'区域年度均值':regional,'Dagum分解及CV':dag,'指标障碍度百分比':obstacle,'子系统障碍度百分比':sysob,'年度平均障碍度':obs_year,'区域平均障碍度':obs_region,'敏感性摘要':sens,'敏感性城市得分':all_sens}
    for name,t in tables.items(): t.to_csv(out/(name+'.csv'),index=False,encoding='utf-8-sig')
    with pd.ExcelWriter(out/'全部实证结果.xlsx',engine='openpyxl') as writer:
        for name,t in tables.items(): t.to_excel(writer,sheet_name=name[:31],index=False)
    fonts={f.name for f in font_manager.fontManager.ttflist}
    plt.rcParams['font.family']='Noto Sans CJK JP' if 'Noto Sans CJK JP' in fonts else 'DejaVu Sans'
    plt.rcParams['axes.unicode_minus']=False
    figs=[]
    def save(name):
        plt.tight_layout(); plt.savefig(out/name,dpi=180,bbox_inches='tight'); plt.close(); figs.append(name)
    plt.figure(figsize=(10,6))
    for city,g in score.groupby('city'): plt.plot(g.year,g['综合指数'],marker='o',ms=3,label=city)
    plt.legend(ncol=3); plt.xlabel('年份'); plt.ylabel('综合TOPSIS贴近度'); plt.title('九市高质量发展综合指数（原始数据基准）'); save('01_综合指数趋势.png')
    latest=score[score.year==2023].sort_values('综合指数',ascending=False)
    plt.figure(figsize=(10,6)); plt.imshow(latest[list(SYSTEMS)],aspect='auto',vmin=0,vmax=1,cmap='YlGnBu'); plt.xticks(range(4),list(SYSTEMS),rotation=15); plt.yticks(range(9),latest.city)
    for i,row in enumerate(latest[list(SYSTEMS)].values):
        for j,v in enumerate(row): plt.text(j,i,f'{v:.3f}',ha='center',va='center',color='black')
    plt.colorbar(label='子系统贴近度'); plt.title('2023年四个子系统（各自评价尺度）'); save('02_子系统热力图.png')
    fig,ax=plt.subplots(1,2,figsize=(12,4.5)); ax[0].plot(dg.year,dg['总体基尼'],'o-',label='基尼'); ax[0].plot(dg.year,dg['变异系数'],'s-',label='CV'); ax[0].legend(); ax[0].set_title('总体差异')
    ax[1].stackplot(dg.year,*[dg[c+'率']*100 for c in ['组内贡献','组间净贡献','超变密度贡献']],labels=['组内','组间净差异','超变密度']); ax[1].legend(); ax[1].set_ylim(0,100); ax[1].set_title('Dagum贡献率（%）'); save('03_区域差异.png')
    grid=np.linspace(0,1,1001); kdrows=[]; fig,axs=plt.subplots(1,3,figsize=(14,4))
    for ax,mul in zip(axs,[.5,1,1.5]):
        for year in [2013,2016,2019,2023]:
            x=score.loc[score.year==year,'综合指数'].values; h=silverman(x)*mul; density=kde_reflected(x,grid,h)
            ax.plot(grid,density,label=str(year)); kdrows.append({'year':year,'带宽倍数':mul,'带宽':h,'数值积分':np.trapezoid(density,grid)})
        ax.set_xlim(0,1); ax.set_title(f'Silverman带宽 × {mul}'); ax.set_xlabel('综合指数'); ax.legend()
    save('04_核密度及带宽敏感性.png'); pd.DataFrame(kdrows).to_csv(out/'核密度带宽.csv',index=False,encoding='utf-8-sig')
    plt.figure(figsize=(10,5)); sy=sysob.groupby('year')[list(SYSTEMS)].mean(); plt.stackplot(sy.index,*[sy[c] for c in SYSTEMS],labels=list(SYSTEMS)); plt.ylim(0,100); plt.legend(loc='upper left'); plt.title('子系统平均障碍度（%）'); save('05_子系统障碍度.png')
    # 一致性检查是实质数值约束，而非零测试占位。
    assert len(score)==99 and score[['综合指数']+list(SYSTEMS)].apply(lambda s:s.between(0,1).all()).all()
    assert np.isclose(w.sum(),1) and (w>=0).all()
    assert np.allclose(ob.sum(axis=1),100)
    assert np.allclose(dag['总体基尼'],dag['组内贡献']+dag['组间净贡献']+dag['超变密度贡献'])
    assert np.allclose(dag[[c+'率' for c in ['组内贡献','组间净贡献','超变密度贡献']]].sum(axis=1),1)
    meta={'input_sha256':hashlib.sha256(args.input.read_bytes()).hexdigest(),'样本数':len(df),'缺失值数':int(df.isna().sum().sum()),'博弈系数':a.tolist(),'博弈方法':method,'基尼_CV年度相关系数':dg['总体基尼'].corr(dg['变异系数']),'数值检查':'99条得分范围、权重归一、障碍度加总、55组Dagum加总及贡献率全部通过','版本':{'numpy':np.__version__,'pandas':pd.__version__}}
    (out/'运行核验.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    write_report(out,df,wt,score,yearly,regional,dg,obstacle,sysob,sens,a,method,audit,meta,figs)
    print(json.dumps(meta,ensure_ascii=False,indent=2)); print('输出目录:',out)

def write_report(out,df,wt,score,yearly,regional,dg,ob,sysob,sens,a,method,audit,meta,figs):
    lines=[]
    def add(s=''): lines.append(s)
    add('# 山东省沿黄九市高质量发展水平、区域差异及障碍因素分析报告')
    add('研究期：2013—2023年。材料：用户提供《思路.docx》及《用于数据清洗的指标汇总13-23.xlsx》。本报告是可复算的实证分析稿，不代替统计来源核验或论文文献综述。')
    y0=yearly.iloc[0]['综合指数']; y1=yearly.iloc[-1]['综合指数']; d0=dg.iloc[0]; d1=dg.iloc[-1]
    add('## 一、主要发现与可信度')
    add(f'原始数据基准下，九市综合指数均值由2013年的{y0:.4f}升至2023年的{y1:.4f}，相对提升{(y1/y0-1)*100:.2f}%。总体基尼由{d0["总体基尼"]:.4f}变为{d1["总体基尼"]:.4f}，CV由{d0["变异系数"]:.4f}变为{d1["变异系数"]:.4f}。这些是评价模型中的相对位置变化，不是经济增长率或因果效应。')
    top=score[score.year==2023].sort_values('综合指数',ascending=False)
    add('2023年排序：'+'、'.join(f'{r.city}（{r.综合指数:.4f}）' for r in top.itertuples())+'。')
    add('结论等级：基于现有表格的可复算结果。旅游消费异常值、能耗单位和排放数据连续性尚待核验；应结合后文敏感性结果使用，不能直接作为已核实的最终论文结论。')
    add('## 二、数据审计与清洗边界')
    add('共99条城市—年份观测，11个数值指标，无空值、无重复城市年份，城市与年份组合完整。仅清理列名空格、核对数值类型并排序；基准不插补、不缩尾、不改原始数值。医疗与图书指标分别已按每千人、每万人计量，沿用实际表头，未误作总量。专利和景区仍为总量，缺少人口分母，存在规模效应。')
    add('济南2015年旅游消费11.9，相邻年份为0.96、1.34，可能影响全样本极值及熵权；不能凭外观认定小数点错误。德州2020年旅游消费为0，既不自动当缺失，也不认定为真实零消费。九市2023年颗粒物排放量全部与2022年一致，可能存在沿用值。单位GDP能耗数值约1075.7—5383.7，表内无单位和分母解释，需核实是否实际为能耗总量。若指标实为总量，绿色解释必须重新评估。')
    add('部分人均GDP、收入和产业占比在2015、2016或2019年前后跳变。可能来自统计修订、行政区划或口径变化，现有文件不足以判断；不能把这些跳变全部解释为实际发展变化。收入、GDP未提供价格平减资料，本报告沿用名义值；跨期提升包含价格因素。旅游指标的单位及“人均”分母也未注明。无外部统计资料交叉验证。')
    add(f'核查清单共{len(audit)}条，见Excel“数据核查清单”；核查不等于判定错误。未进行机械异常剔除，以免删除疫情期等真实波动。')
    add('## 三、方法、公式与复算口径')
    add('全部99条观测共同确定极差标准化基准。正向 z=(x−min)/(max−min)，负向 z=(max−x)/(max−min)，单位GDP能耗与颗粒物排放为负向，其余正向。熵权 p=z/Σz，0ln0按0处理，e=−Σp ln p/ln99，w=(1−e)/Σ(1−e)。CRITIC采用标准化值的总体标准差和Pearson相关：C_j=σ_jΣ_k(1−r_jk)，再归一化。')
    add(f'博弈组合：令W两行分别为熵权和CRITIC权重，A=WWᵀ，解Aα=diag(A)，再将非负系数归一化；α=({a[0]:.6f}, {a[1]:.6f})。实际使用：{method}。若未来数据产生负系数，程序使用单纯形约束残差最小化并明确披露，不能将其称作经典无约束均衡。')
    add('TOPSIS采用加权极差标准化矩阵v=z·w，固定全样本正负理想点v⁺、v⁻，以欧氏距离计算H=D⁻/(D⁺+D⁻)。这是先乘权重再求平方距离的版本；距离中的有效系数为w²，不混用Σw(z−z⁺)²的另一版本。各子系统内部权重重新归一化，各自使用全样本理想点。综合指数不等于子系统指数的加权平均；不同子系统有不同理想目标，不能把其数值差直接解释为现实单位差距。')
    add('Dagum按每年九市等权分解。G=Σ_iΣ_j|H_i−H_j|/(2n²μ)。每组内绝对差除以2n²μ得到组内贡献；每对区域的绝对差和除以n²μ得到组对总贡献，其中差值和的绝对值除以n²μ为组间净贡献，余项为超变密度。等价于Dagum的G_jh(p_j s_h+p_h s_j)D_jh与(1−D_jh)分配；超变密度刻画分布交叉。每年检验G=G_w+G_nb+G_t。CV=总体标准差/均值（ddof=0）；与基尼趋势比较只作辅助，不是独立因果检验。')
    add('地理三区为研究者分析分组：鲁中引领区（济南、泰安、淄博），鲁北生态转型区（东营、滨州、德州），鲁西及鲁西南协同发展区（菏泽、济宁、聊城）。不是官方行政划分，组间比较还受分组方式影响。')
    add('核密度在2013、2016、2019、2023年各取9个城市，不跨年池化。Gaussian核，Silverman带宽h=0.9min(s,IQR/1.34)n^(−1/5)，s为样本标准差，IQR为零时回退s；采用[0,1]边界反射，比较0.5h、h和1.5h。每期仅9个样本，不据多峰断言极化。障碍度O_j=w_j(1−z_j)/Σw_k(1−z_k)×100%，子系统相加，区域和九市总体取城市障碍度算术平均；不是先聚合原始指标再计算障碍度。')
    add('## 四、权重与发展水平')
    add(df_table(wt[['指标','子系统','熵权','CRITIC权重','组合权重']]))
    groupw=wt.groupby('子系统')['组合权重'].sum().sort_values(ascending=False)
    add('子系统全局权重合计：'+'；'.join(f'{k}{v:.2%}' for k,v in groupw.items())+'。客观赋权衡量样本中的区分信息，不代表政策重要性或因果贡献。')
    add('### 年度均值与演变')
    add(df_table(yearly))
    for name in SYSTEMS:
        v0=yearly.iloc[0][name]; v1=yearly.iloc[-1][name]
        lead=score[score.year==2023].sort_values(name,ascending=False).iloc[0]
        add(f'{name}：九市均值由{v0:.4f}变为{v1:.4f}，2023年最高为{lead.city}（{lead[name]:.4f}）。')
    add('创新子系统均值2023年较2022年回落，表中专利授权数九市均下降；这是指标层面的共同变化，尚不能区分授权周期、统计调整或实际创新变化。济南绿色子系统相对经济与创新表现偏弱，东营则呈经济与绿色突出、创新指标偏弱的结构。滨州绿色优势依赖现有能耗口径，应先核实后作政策解释。')
    add('### 2023年城市水平及排名')
    add(df_table(top[['city','综合指数','年度排名']+list(SYSTEMS)]))
    add('各市2013—2023完整得分、年度排名、四子系统得分见结果工作簿。采用统一基准和固定权重保障本样本跨年可比；加入未来年份后重算极值或权重会改变历史得分。')
    add('### 三区域均值比较')
    reg=regional[regional.year.isin([2013,2023])]
    add(df_table(reg))
    add('区域均值为三市等权平均，不按人口或GDP加权。领先区域并不意味着其每个城市都领先其他区域，须结合超变密度理解分布交叉。')
    add('## 五、区域差异及动态分布')
    add(df_table(dg[['year','总体基尼','组内贡献','组间净贡献','超变密度贡献','组内贡献率','组间净贡献率','超变密度贡献率','变异系数']]))
    source=d1[['组内贡献','组间净贡献','超变密度贡献']].astype(float).idxmax()
    add(f'2023年差异来源中{source}最大。基尼与CV的11个年度水平相关系数为{meta["基尼_CV年度相关系数"]:.4f}。需逐年看共同变化及拐点，相关系数高仅表明两项离散度测度在本样本走势接近，不是显著性或独立样本验证。四个子系统逐年Dagum分解也已导出，可用于扩展比较。')
    changes=dg['总体基尼'].diff().dropna(); reversals=(np.sign(changes).diff().abs()>0).sum()
    add(f'总体基尼并非假定为单调过程：11年中上升{int((changes>0).sum())}次、下降{int((changes<0).sum())}次，趋势描述应同时交代阶段波动。')
    for year in [2013,2016,2019,2023]:
        xx=score.loc[score.year==year,'综合指数'].to_numpy()
        add(f'{year}年综合指数中位数{np.median(xx):.4f}，取值范围[{xx.min():.4f}, {xx.max():.4f}]，总体标准差{xx.std(ddof=0):.4f}。')
    add('从图4可见主峰总体右移，2023年右尾延伸更明显，与均值提高及离散度扩大相符。0.5倍带宽出现较多小峰，1.5倍带宽明显平滑，说明峰数对平滑参数敏感，不能认定形成稳定的双极或多极结构。')
    add('核密度图与带宽敏感性图见图4。应结合均值、基尼和城市实际位置解释：曲线位置和峰形受带宽显著影响，不能凭九个城市的平滑曲线识别稳定的极化机制。反射修正降低有界得分的边界泄漏，细节见“核密度带宽.csv”。')
    add('## 六、障碍因素及差异化路径')
    for year in [2013,2016,2019,2023]:
        avg=ob[ob.year==year][COLS].mean().sort_values(ascending=False)
        add(f'{year}年九市平均前三项障碍：'+'；'.join(f'{k} {v:.2f}%' for k,v in avg.iloc[:3].items())+'。')
    add('基准旅游指标因济南2015年极值11.9而使多数城市距理想点较远，这会抬高其障碍度的相对意义。高障碍排序同时受权重和标准化目标影响，必须在旅游口径核实后复算，不宜直接归因于旅游发展不足。')
    add('### 2023年城市前三项障碍')
    cityrows=[]
    for _,r in ob[ob.year==2023].iterrows():
        v=r[COLS].astype(float).sort_values(ascending=False)
        cityrows.append({'城市':r.city,'第一障碍':f'{v.index[0]} {v.iloc[0]:.2f}%','第二障碍':f'{v.index[1]} {v.iloc[1]:.2f}%','第三障碍':f'{v.index[2]} {v.iloc[2]:.2f}%'})
    add(df_table(pd.DataFrame(cityrows)))
    add('### 2023年子系统障碍与三区差异')
    add(df_table(sysob[sysob.year==2023].groupby('区域')[list(SYSTEMS)].mean().reset_index()))
    for region,g in ob[ob.year==2023].groupby('区域'):
        v=g[COLS].mean().sort_values(ascending=False)
        add(f'{region}的平均主要短板为{v.index[0]}（{v.iloc[0]:.2f}%）和{v.index[1]}（{v.iloc[1]:.2f}%）。可优先核查这两项供给、统计质量及城市内部差异，再配置改善资源；不能将高障碍度解释为提高该指标即可产生相同比例的综合发展收益。')
    add('政策含义：经济维度兼顾收入与生产率，创新维度关注专利质量和成果转化而非单纯数量，绿色维度先核实能耗口径并推进单位产出节能减排，民生维度关注床位和图书服务可及性。鲁中应强化创新成果扩散和都市圈公共服务协作；鲁北应结合能源产业转型和生态约束提升增长质量；鲁西及鲁西南可加强创新资源承接和基本公共服务。上述为指标诊断导向的建议，仍需财政、人口、产业和政策资料支持具体项目选择。')
    add('## 七、异常值敏感性与结果边界')
    add('对济南2015年旅游值以相邻年份均值1.15作假设插值；对德州2020年以相邻年份均值0.365作假设插值；分别与联合插值、剔除旅游指标、全样本旅游1%—99%缩尾比较。每种情景独立重算标准化、熵权、CRITIC、组合权重和理想点。剔除情景将旅游标准化列置零，熵权及CRITIC均不计其信息，数学上等价于移除该指标。结果不是确认的修正值。')
    add(df_table(sens))
    s=sens[sens['情景']=='两处旅游联合插值'].iloc[0]
    add(f'联合插值下，2023年城市排名与基准Spearman相关系数为{s["2023排名Spearman"]:.4f}，最大名次变化{int(s["2023最大名次变化"])}位。不同情景的指数水平因基准及权重变化不宜当作同一量尺直接作差；应重点比较城市排序和差异方向。')
    direction=sens['2023基尼']-sens['2013基尼']
    add('各旅游敏感性情景的期末—期初基尼变化'+('方向一致。' if (direction>0).all() or (direction<0).all() else '方向不完全一致，区域差异趋势对数据处理敏感。'))
    add('旅游核查不能解决能耗口径、颗粒物沿用值或统计区划跳变的不确定性。未按猜测修改这些值，也未为2013年不明小数精度虚构来源。下一步应回查原始统计年鉴、统一能耗及旅游消费单位、确认2019年前后GDP口径与济南区划可比性，补入人口以检验专利/景区规模效应、补入价格指数以区分实际与名义提升，再冻结论文最终版本。')
    add('## 八、复现与验证')
    add('代码入口analysis.py；Python 3.11或3.12，使用requirements.txt中的固定依赖，执行python analysis.py即可从data/input.xlsx重算全部表格、图像、Markdown及Word报告。输入路径和输出路径可通过--input、--output指定。原文件随包保留，SHA256见运行核验.json。')
    add('已执行的验证：'+meta['数值检查']+'。独立单元测试覆盖已知Dagum解析值、分解的排列与尺度不变性、TOPSIS理想点，以及核密度面积；测试结果由终端记录。无随机估计，无外部API依赖，无耦合协调模型。')
    add('本报告没有对城市样本作总体抽样推断，没有估计因果效应，没有引用未经核验的外部文献。报告与全部中间数据均由同一脚本生成，便于补充核实数据后重跑。')
    add('## 图表')
    for fn in figs: add(f'![{fn}]({fn})')
    text='\n\n'.join(lines); (out/'分析报告.md').write_text(text,encoding='utf-8')
    doc=Document(); sec=doc.sections[0]; sec.header.paragraphs[0].text='沿黄九市 · 实证分析与数据质量说明'
    normal=doc.styles['Normal']; normal.font.name='SimSun'
    from docx.oxml.ns import qn
    normal.element.rPr.rFonts.set(qn('w:eastAsia'),'宋体')
    for block in lines:
        if block.startswith('#'):
            level=len(block)-len(block.lstrip('#')); doc.add_heading(block[level:].strip(),level=min(level,3))
        elif block.startswith('|'):
            rows=block.splitlines(); headers=[x.strip() for x in rows[0].strip('|').split('|')]
            t=doc.add_table(rows=1,cols=len(headers)); t.style='Light Shading Accent 1'
            for cell,v in zip(t.rows[0].cells,headers): cell.text=v
            for row in rows[2:]:
                for cell,v in zip(t.add_row().cells,row.strip('|').split('|')): cell.text=v.strip()
        elif block.startswith('!['):
            fn=block.split('](')[1][:-1]; doc.add_picture(str(out/fn),width=Inches(6))
        else: doc.add_paragraph(block)
    doc.save(out/'分析报告.docx')

if __name__=='__main__': main()
