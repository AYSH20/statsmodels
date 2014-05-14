#import cython
#import glob
import pandas as pd
import numpy as np
import sys
sys.path.insert(0,"C:/Users/Frank/Documents/GitHub/statsmodels/")
#import copy

class ImputedData:
    """
    Initialize a data object with missing data information and functionality
    to insert values in missing data slots.
    """
    def __init__(self, data):
        self.data = pd.DataFrame(data)
        self.values = {}
        self.mean = {}
        for c in self.data.columns:
            null = pd.isnull(self.data[c])
            ix_miss = np.flatnonzero(null)
            ix_obs = np.flatnonzero(~null)
            if len(ix_obs) == 0:
                raise ValueError("Variable has no observed values")
            val =  np.zeros(len(ix_miss), dtype=self.data.dtypes)
            self.values[c] = [ix_obs, ix_miss, val]

    def store_changes(self, col):
       ix = self.values[col][1]
       v = self.values[col][2]
       self.data[col][ix] = v

class Imputer:
    """
    Initializes object that imputes values for a single variable using a given formula
    """
    def __init__(self, data, formula, model_class, init_args={}, fit_args={}):
        self.data = data
        self.formula = formula
        self.model_class = model_class
        self.init_args = init_args
        self.fit_args = fit_args
        self.endog_name = str(self.formula.split("~")[0].strip())

    # Impute the dependent variable once
    def impute_asymptotic_bayes(self):
        ix = self.data.values[self.endog_name][1]
        io = self.data.values[self.endog_name][0]
        md = self.model_class.from_formula(self.formula, self.data.data.ix[io], **self.init_args)
        mdf = md.fit(**self.fit_args)
        exog_name = md.exog_names[1:]
        params = mdf.params.copy()
        covmat = mdf.cov_params()
        covmat_sqrt = np.linalg.cholesky(covmat)
        u = np.random.chisquare(mdf.df_resid)
        #later check if model is likelihood, if there is scale, etc instead of this
        try:
            mdf.mse_resid
            scale_per = mdf.df_resid/u
        except:
            scale_per = 1

        p = len(params)
        params += np.dot(covmat_sqrt, np.random.normal(0,scale_per,p))
        #change to md.exog so that transformations are handled
        #PROBLEM: How to apply md.exog's transformations to the exogs for the missing endog?
        #Idea: fit another model with all obs but costly? look into how formula is applied in statsmodels
#        exog = pd.DataFrame(md.exog)
#        c = ['Intercept']
#        c.extend(exog_name)
#        exog.columns = c
        exog = self.data.data[exog_name].ix[ix]
        endog_obj = md.get_distribution(params=params, exog=exog, scale=scale_per)
        new_endog = endog_obj.rvs()
        self.data.values[self.endog_name][2] = new_endog
        self.data.store_changes(self.endog_name)

class ImputerChain:
    """
    Manage a collection of imputers for variables in a common dataframe.
    This class does imputation and stores the imputed data sets, it does not fit
    the analysis model.

    Note: All imputers must refer to the same data object
    """
    def __init__(self, imputer_list, iternum, skipnum):
        #PROBLEM: Scope means that using self.data = imputer_list[0].data.data will only change data within the class.
        #The version of data imputer modifies is outisde the class.
        self.imputer_list = imputer_list
        #All imputers must refer to the same data object
        self.imputer_list[0].data.data = self.imputer_list[0].data.data.fillna(self.imputer_list[0].data.data.mean())
        self.inum = iternum
        self.snum = skipnum
        self.c = 0

    def __iter__(self):
        return self

    # Impute each variable once, initialize missing values to column means
    def next(self):
        if self.c >= self.inum:
            raise StopIteration
        for j in range(self.snum):
            for im in self.imputer_list:
                im.impute_asymptotic_bayes()
            #self.store_changes()
        self.c = self.c + 1
        print(self.c)
        return self.imputer_list[0].data.data

    # Don't need this because impute_asymptotic_bayes updates the dataset every time it runs, as desired.
#    def store_changes(self):
#        for im in self.imputer_list:
#            im.data.store_changes()

    # Impute data sets and save them to disk, keep this around for now
#    def generate_data(self, num, skip, base_name):
#        for k in range(num):
#            for j in range(skip):
#                self.next()
#            fname = "%s_%d.csv" % (base_name, k)
#            self.imputer_list[0].data.data.to_csv(fname, index=False)
#            self.values.append(copy.deepcopy(self.imputer_list[self.implength - 1].data.values))
#            #self.imputer_list[0].data.mean_fill()


class MICE:
    """
    Fits the analysis model to each imputed dataset and combines the results using Rubin's rule.
    """
    def __init__(self, imputer_chain, analysis_formula, analysis_class,
                 init_args={}, fit_args={}):
        self.imputer_chain = imputer_chain
        self.formula = analysis_formula
        self.analysis_class = analysis_class
        self.init_args = init_args
        self.fit_args = fit_args
        self.iternum = imputer_chain.inum

    def combine(self):
        params_list = []
        std_list = []
        for data in self.imputer_chain:
            md = self.analysis_class.from_formula(self.formula, data, **self.init_args)
            mdf = md.fit(**self.fit_args)
            params_list.append(mdf.params)
            std_list.append(mdf.bse)
        params = np.mean(params_list, axis = 0)
        within_g = np.mean(std_list, axis = 0)
        between_g = np.std(params_list, axis = 0)
        std = within_g + (1 + 1/self.iternum) * between_g
        #TODO: return results class
        return params, std

class AnalysisChain:
    """
    Imputes and fits analysis model without saving intermediate datasets.
    """

    def __init__(self, imputer_list, analysis_formula, analysis_class,
                 init_args={}, fit_args={}):
        self.imputer_list = imputer_list
        self.analysis_formula = analysis_formula
        self.analysis_class = analysis_class
        self.init_args = init_args
        self.fit_args = fit_args
        self.imputer_list[0].data.data = self.imputer_list[0].data.data.fillna(self.imputer_list[0].data.data.mean())

    def cycle(self):
        for im in self.imputer_list:
            im.impute_asymptotic_bayes()

    def run_chain(self, num, skip):
        params_list = []
        std_list = []
        for k in range(num):
            for j in range(skip):
                self.cycle()
            md = self.analysis_class.from_formula(self.analysis_formula,self.imputer_list[0].data.data,**self.init_args)
            mdf = md.fit(**self.fit_args)
            params_list.append(mdf.params)
            std_list.append(mdf.bse)
        params = np.mean(params_list, axis = 0)
        within_g = np.mean(std_list, axis = 0)
        between_g = np.std(params_list, axis = 0)
        std = within_g + (1 + 1/num) * between_g
        #TODO: return results class
        return params, std
