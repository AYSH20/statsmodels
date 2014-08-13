import numpy as np
import pandas as pd
from statsmodels.sandbox.mice import mice
import statsmodels.api as sm
import os

def load_data():
    """
    Load a data set from the results directory, generated by R mice routine.
    """

    params = pd.io.parsers.read_csv("params.csv")
    params.columns = ['int', 'x2']
    cov = pd.io.parsers.read_csv("cov.csv")
    cov.columns = ['int', 'x2']
    data = pd.io.parsers.read_csv("missingdata.csv")
    data.columns = ['x1', 'x2']

    return params,cov,data

class TestMice(object):
    def __init__(self):
        self.formula = "X2~X3+X4"

    def test_get_data_from_formula(self):
        np.random.seed(1325)
        data = np.random.normal(size=(10,4))
        data[8:, 1] = np.nan
        df = pd.DataFrame(data, columns=["X1", "X2", "X3", "X4"])
        imp_dat = mice.ImputedData(df)
        endog_obs, exog_obs, exog_miss = imp_dat.get_data_from_formula(
                                                            self.formula)
        endog_obs, exog_obs, exog_miss = imp_dat.get_data_from_formula(
                                                            self.formula)
        endog_obs = np.asarray(endog_obs).flatten()
        exog_obs = np.asarray(exog_obs)[:,1:]
        exog_miss = np.asarray(exog_miss)[:,1:]
        test_exog_obs = data[0:8,2:]
        test_exog_miss = data[-2:,2:]
        test_endog_obs = data[0:8,1]
        np.testing.assert_almost_equal(exog_obs, test_exog_obs)
        np.testing.assert_almost_equal(exog_miss, test_exog_miss)
        np.testing.assert_almost_equal(endog_obs, test_endog_obs)

    def test_store_changes(self):
        np.random.seed(1325)
        data = np.random.normal(size=(10,4))
        data[8:, 1] = np.nan
        df = pd.DataFrame(data, columns=["X1", "X2", "X3", "X4"])
        imp_dat = mice.ImputedData(df)
        imp_dat.store_changes("X2", [0] * 2)
        test_data = np.asarray(imp_dat.data["X2"][8:])
        np.testing.assert_almost_equal(test_data, np.asarray([0., 0.]))
#
    def test_perturb_params(self):
        np.random.seed(1325)
        data = np.random.normal(size=(10,4))
        data[8:, 1] = np.nan
        df = pd.DataFrame(data, columns=["X1", "X2", "X3", "X4"])
        params_test = np.asarray([-0.06523173,  0.37082165, -0.68803828])
        scale_test = 1.0
        md = sm.OLS.from_formula(self.formula, df)
        mdf = md.fit()
        imputer = mice.Imputer(self.formula, sm.OLS, mice.ImputedData(df))
        params, scale_per = imputer.perturb_params(mdf)
        params = np.asarray(params)
        np.testing.assert_almost_equal(params, params_test)
        np.testing.assert_almost_equal(scale_per, scale_test)

    def test_impute_asymptotic_bayes(self):
        np.random.seed(1325)
        data = np.random.normal(size=(10,4))
        data[8:, 1] = np.nan
        df = pd.DataFrame(data, columns=["X1", "X2", "X3", "X4"])
        imputer = mice.Imputer(self.formula, sm.OLS, mice.ImputedData(df))
        imputer.impute_asymptotic_bayes()
        np.testing.assert_almost_equal(np.asarray(imputer.data.data['X2'][8:]),
                                       np.asarray([-0.83679515, -0.22187195]))

    def test_impute_pmm(self):
        np.random.seed(1325)
        data = np.random.normal(size=(10,4))
        data[8:, 1] = np.nan
        df = pd.DataFrame(data, columns=["X1", "X2", "X3", "X4"])
        imputer = mice.Imputer(self.formula, sm.OLS, mice.ImputedData(df))
        imputer.impute_pmm()
        np.testing.assert_almost_equal(np.asarray(imputer.data.data['X2'][8:]),
                                       np.asarray([-0.77954822, -0.77954822]))

    def test_combine(self):
        np.random.seed(1325)
        data = np.random.normal(size=(10,4))
        data[8:, 1] = np.nan
        df = pd.DataFrame(data, columns=["X1", "X2", "X3", "X4"])
        impdata = mice.ImputedData(df)
        m = impdata.new_imputer("X2", scale_method="perturb_chi2", method="pmm")
        impcomb = mice.MICE("X2 ~ X1 + X3", sm.OLS, [m])
        impcomb.run()
        p1 = impcomb.combine()
        np.testing.assert_almost_equal(p1.params, np.asarray([0.31562745, 
                                                              0.19100593,
                                                              0.0133906 ]))
        np.testing.assert_almost_equal(p1.scale, 0.61329459165397548)
        np.testing.assert_almost_equal(p1.cov_params(), np.asarray([
        [  7.88964139e-02,   2.70237318e-02,  -3.64367780e-03],
        [  2.70237318e-02,   7.23763179e-02,  -1.76877602e-05],
        [ -3.64367780e-03,  -1.76877602e-05,   6.80019669e-02]]))

    def test_nomissing(self):
    
        n, p = 100, 5
        data = np.random.normal(size=(n, p))
        data[:,-1] = data.sum(1)
        data = pd.DataFrame(data, columns=["X1", "X2", "X3", "X4", "Y"])

        imp_data = mice.ImputedData(data)
        imputers = [imp_data.new_imputer(name) for name in data.columns]

        mice_mod = mice.MICE("Y ~ X1 + X2 + X3 + X4", sm.OLS, imputers)
        mice_mod.run()
        mice_rslt = mice_mod.combine()

        ols_mod = sm.OLS.from_formula("Y ~ X1 + X2 + X3 + X4", data)
        ols_rslt = ols_mod.fit()

        np.testing.assert_almost_equal(mice_rslt.params,
                                       ols_rslt.params)
        np.testing.assert_almost_equal(mice_rslt.cov_params(),
                                       ols_rslt.cov_params())
        np.testing.assert_almost_equal(mice_rslt.bse, ols_rslt.bse)
        
    def test_overall(self):
        """
        R code used for comparison:

        N<-250;
        x1<-rbinom(N,1,prob=.4)  #draw from a binomial dist with probability=.4
        x2<-rnorm(N,0,1)         #draw from a normal dist with mean=0, sd=1
        x3<-rnorm(N,-10,1)
        y<--1+1*x1-1*x2+1*x3+rnorm(N,0,1)  #simulate linear regression data with a normal error (sd=1)
        
        #Generate MAR data
        
        alpha.1<-exp(16+2*y-x2)/(1+exp(16+2*y-x2));
        alpha.2<-exp(3.5+.7*y)/(1+exp(3.5+.7*y));
        alpha.3<-exp(-13-1.2*y-x1)/(1+exp(-13-1.2*y-x1));
        
        
        r.x1.mar<-rbinom(N,1,prob=alpha.1)
        r.x2.mar<-rbinom(N,1,prob=alpha.2)
        r.x3.mar<-rbinom(N,1,prob=alpha.3)
        x1.mar<-x1*(1-r.x1.mar)+r.x1.mar*99999  #x1.mar=x1 if not missing, 99999 if missing
        x2.mar<-x2*(1-r.x2.mar)+r.x2.mar*99999
        x3.mar<-x3*(1-r.x3.mar)+r.x3.mar*99999
        x1.mar[x1.mar==99999]=NA                  #change 99999 to NA (R's notation for missing)
        x2.mar[x2.mar==99999]=NA
        x3.mar[x3.mar==99999]=NA
        
        require(mice)
        data = as.data.frame(cbind(x1.mar,x2.mar,x3.mar))
        data$x1.mar = as.factor(data$x1.mar)
        nrep = 500
        params = array(0, nrep)
        imp_pmm = mice(data, m=20, maxit=10, method="pmm")
        fit = with(data=imp_pmm,exp=glm(x1.mar~x2.mar + x3.mar,family=binomial))
        pooled = pool(fit)
        print(summary(pooled))
        
        setwd("C:/Users/Frank/Documents/GitHub/statsmodels/statsmodels/sandbox/mice/tests")
        write.csv(cbind(pooled$u[1:20], pooled$u[81:100], pooled$u[161:180]), "cov.csv", row.names=FALSE)
        write.csv(pooled$qhat, "params.csv", row.names=FALSE)
        write.csv(data, "missingdata.csv", row.names=FALSE)
        """
        params,cov,data = load_data()
        r_pooled_se = np.asarray(cov)
#        np.sqrt(np.asarray(np.mean(cov) + (1 + 1 / 20.) * np.var(params)))
        r_pooled_params = np.asarray(np.mean(params))
        impdata = mice.ImputedData(data)
        impdata.new_imputer("x2", method="pmm", k_pmm=20)
#        impdata.new_imputer("x3", method="pmm", k_pmm=20)
        impdata.new_imputer("x1", model_class=sm.Logit, method="pmm", k_pmm=20)
        impcomb = mice.MICE("x1 ~ x2", sm.Logit, impdata)
        impcomb.run(20,10)
        p1 = impcomb.combine()
        print p1.summary()        
        np.testing.assert_allclose(p1.params, r_pooled_params, rtol=0.4)
        np.testing.assert_allclose(np.sqrt(np.diag(p1.cov_params())), r_pooled_se, rtol=0.3)

if  __name__=="__main__":

    import nose

    nose.runmodule(argv=[__file__,'-vvs','-x','--pdb', '--pdb-failure'],
                   exit=False)
