import unittest
import numpy as np
from analysis import dagum,topsis,kde_reflected,silverman,load_data,evaluate,COLS
from pathlib import Path

class MethodsTest(unittest.TestCase):
    def test_dagum_known_crossing(self):
        # A={1,4}, B={2,3}：G=20/80=.25，组内=.10，组间均值相等，超变=.15。
        r=dagum([1,4,2,3],['A','A','B','B'])
        for key,value in [('总体基尼',.25),('组内贡献',.1),('组间净贡献',0),('超变密度贡献',.15)]: self.assertAlmostEqual(r[key],value)
    def test_dagum_nonoverlap(self):
        r=dagum([1,2,3,4],['A','A','B','B'])
        self.assertAlmostEqual(r['组内贡献'],.05)
        self.assertAlmostEqual(r['组间净贡献'],.2)
        self.assertAlmostEqual(r['超变密度贡献'],0)
    def test_dagum_scale_and_permutation(self):
        r=dagum([1,4,2,3],['A','A','B','B']); s=dagum([30,10,20,40],['B','A','B','A'])
        for k in ['总体基尼','组内贡献','组间净贡献','超变密度贡献']: self.assertAlmostEqual(r[k],s[k])
    def test_topsis_ideal_points(self):
        np.testing.assert_allclose(topsis(np.array([[0.,0.],[.5,.5],[1.,1.]]),[.2,.8]),[0,.5,1])
    def test_kde_mass(self):
        x=np.array([.01,.04,.1,.2,.3,.4,.5,.7,.9]); grid=np.linspace(0,1,10001)
        f=kde_reflected(x,grid,silverman(x))
        self.assertAlmostEqual(np.trapezoid(f,grid),1,places=5)
    def test_panel_real_data(self):
        d=load_data(Path(__file__).parent/'data/input.xlsx'); *_,s=evaluate(d)
        self.assertEqual(len(s),99)
        self.assertEqual(d.loc[(d.city=='济南')&(d.year==2015),COLS[-1]].iloc[0],11.9)
        self.assertEqual(d.loc[(d.city=='德州')&(d.year==2020),COLS[-1]].iloc[0],0)

if __name__=='__main__': unittest.main(verbosity=2)
