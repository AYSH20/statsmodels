"""
This module implements the Multiple Imputation through Chained Equations (MICE)
approach to handling missing data. This approach has 3 steps in general:

1) Simulate observations using a user specified conditional model.
2) Fit the model of interest to a compelte, simulated dataset.
3) Repeat N times combine the N models according to Rubin's Rules.

Imputer instances, for imputing a single missing variable,
are specified with a (statsmodels) conditional model
(default is OLS with all other variables). A MICE instance is specified with
a model of interest together with its corresponding formulae. The results are
combined using the `combine` method.

Reference for Rubin's Rules and Multiple Imputation:

J L Schafer: "Multiple Imputation: A Primer", Stat Methods Med Res, 1999.

Reference for Gaussian Approximation to the Posterior:

T E Raghunathan et al.: "A Multivariate Technique for Multiply
Imputing Missing Values Using a Sequence of Regression Models",
Survey Methodology, 2001.

Reference for Predictive Mean Matching:

SAS Institute: "Predictive Mean Matching Method for Monotone Missing Data",
SAS 9.2 User's Guide, 2014.

"""

import random
import operator
import pandas as pd
import numpy as np
import sys
#run from local directory
sys.path.insert(0, "C:/Users/Frank/Documents/GitHub/statsmodels/")
import statsmodels.api as sm

class ImputedData(object):
    __doc__= """
    Stores missing data information and supports functionality for
    inserting values in missing data slots. Can create Imputers directly.

    %(params)s
    data : array-like object
        Needs to support transformation to pandas dataframe. Missing value
        encoding is handled by pandas DataFrame class.

    **Attributes**

    data : pandas dataframe
        Dataset with missing values. After recording missing data information,
        simple column-wise means are filled into the missing values.
    columns : dictionary
        Stores indices of missing data.
    """
    def __init__(self, data):
        self.data = pd.DataFrame(data)
        self.columns = {}
        for c in self.data.columns:
            self.columns[c] = MissingDataInfo(self.data[c])
        self.data = self.data.fillna(self.data.mean())

    def new_imputer(self, endog, formula=None, model_class=None, init_args={}, fit_args={}, scale="fix", scale_value=None):
        """
        Create Imputer instance from our ImputedData instance

        Parameters
        ----------
        endog : string
            Name of the variable to be imputed.
        formula : string
            Conditional formula for imputation.
        model_class : statsmodels model
            Conditional model for imputation
        scale : string
            Governs the type of perturbation given to the scale parameter.
        scale_value : float
            Fixed value of scale parameter to use in simulation of data.

        Returns
        -------
        mice.Imputer object

        See Also
        --------
        mice.Imputer
        """
        if model_class is None:
            model_class = sm.OLS
        if formula is None:
            default_formula = endog + " ~ " + " + ".join([x for x in self.data.columns if x != endog])
            return Imputer(default_formula, model_class, self, init_args=init_args, fit_args=fit_args, scale=scale,scale_value=scale_value)
        else:
            formula = endog + " ~ " + formula
            return Imputer(formula, model_class, self, init_args=init_args, fit_args=fit_args, scale=scale,scale_value=scale_value)

    def store_changes(self, vals, col=None):
        """
        Fill in dataset with imputed values

        Parameters
        ----------
        vals : array
            Array of imputed values to use in filling in missing values.
        col : string
            Name of variable to be filled in.
        """
        if col==None:
            for c in self.columns.keys():
                ix = self.columns[c].ix_miss
                self.data[c].iloc[ix] = vals
        else:
            ix = self.columns[col].ix_miss
            self.data[col].iloc[ix] = vals

class Imputer(object):

    __doc__= """
    Initializes object that imputes values for a single variable
    using a given formula.

    %(params)s

    formula : string
        Conditional formula for imputation.
    model_class : statsmodels model
        Conditional model for imputation.
    data : ImputedData object
        See mice.ImputedData
    scale : string
        Governs the type of perturbation given to the scale parameter.
    scale_value : float
        Fixed value of scale parameter to use in simulation of data.
    %(extra_params)s

    **Attributes**

    endog_name : string
        Name of variable to be imputed.
    num_missing : int
        Number of missing values.
    """
    def __init__(self, formula, model_class, data, init_args={}, fit_args={},
                 scale="fix", scale_value=None):
        self.data = data
        self.formula = formula
        self.model_class = model_class
        self.init_args = init_args
        self.fit_args = fit_args
        self.endog_name = str(self.formula.split("~")[0].strip())
        self.num_missing = len(self.data.columns[self.endog_name].ix_miss)
        self.scale = scale
        self.scale_value = scale_value

    def impute_asymptotic_bayes(self):
        """
        Use Gaussian approximation to posterior distribution to simulate data.
        """
        io = self.data.columns[self.endog_name].ix_obs
        md = self.model_class.from_formula(self.formula, self.data.data.iloc[io,:], **self.init_args)
        mdf = md.fit(**self.fit_args)
        params = mdf.params.copy()
        covmat = mdf.cov_params()
        covmat_sqrt = np.linalg.cholesky(covmat)
        if self.scale == "fix":
            if self.scale_value is None:
                scale_per = 1.
            else:
                scale_per = self.scale_value
        elif self.scale == "perturb_chi2":
            u = np.random.chisquare(mdf.df_resid)
            scale_per = mdf.df_resid/u
        elif self.scale == "perturb_boot":
            pass
        p = len(params)
        params += np.dot(covmat_sqrt, np.random.normal(0, scale_per * mdf.scale, p))
        imiss = self.data.columns[self.endog_name].ix_miss
        #TODO: find a better way to determine if first column is intercept
        exog_name = md.exog_names[1:]
        exog = self.data.data[exog_name].iloc[imiss,:]
        endog_obj = md.get_distribution(params=params, exog=exog, scale=scale_per * mdf.scale)
        new_endog = endog_obj.rvs()
        self.data.store_changes(new_endog, self.endog_name)

    def impute_pmm(self, k0=1):
        """
        Use predictive mean matching to simulate data.
        """
        io = self.data.columns[self.endog_name].ix_obs
        md = self.model_class.from_formula(self.formula, self.data.data.iloc[io,:], **self.init_args)
        mdf = md.fit(**self.fit_args)
        params = mdf.params.copy()
        covmat = mdf.cov_params()
        covmat_sqrt = np.linalg.cholesky(covmat)
        if self.scale == "fix":
            if self.scale_value is None:
                scale_per = 1
            else:
                scale_per = self.scale_value
        elif self.scale == "perturb_chi2":
            u = np.random.chisquare(mdf.df_resid)
            scale_per = scale_per = mdf.df_resid/u
        elif self.scale == "perturb_boot":
            pass
        p = len(params)
        params += np.dot(covmat_sqrt, np.random.normal(0, mdf.scale * scale_per, p))
        #find a better way to determine if first column is intercept
        exog_name = md.exog_names[1:]
        exog = self.data.data[exog_name]
        exog.insert(0, 'Intercept', 1)
        endog_all = md.predict(params,exog)
        endog_matched = []
        imiss = self.data.columns[self.endog_name].ix_miss
        for mval in endog_all[imiss]:
            dist = abs(endog_all - mval)
            dist = sorted(range(len(dist)), key=lambda k: dist[k])
            endog_matched.append(random.choice(np.array(self.data.data[self.endog_name][dist[len(imiss):len(imiss) + k0]])))
        new_endog = endog_matched
        self.data.store_changes(new_endog, self.endog_name)

    def impute_bootstrap(self):
        pass

#TODO: put imputer type, optional params into this class
class ImputerChain(object):
    __doc__= """
    Manage a collection of imputers for variables in a common dataframe.
    This class does imputation and returns the imputed data sets, it does not fit
    the analysis model. Meant to be used as an iterator for the MICE class.

    %(params)s

    imputer_list : list
        List of Imputer objects, one for each variable to be imputed.

    **Attributes**

    data : pandas DataFrame
        Underlying data to be modified.

    Note: All imputers must refer to the same data object
    """
    def __init__(self, imputer_list):
        self.imputer_list = imputer_list
        #Impute variable with least missing observations first
        self.imputer_list.sort(key=operator.attrgetter('num_missing'))
        #All imputers must refer to the same data object
        self.data = imputer_list[0].data.data


    def __iter__(self):
        return self

    def next(self):
        """
        Makes this class an iterator that returns imputed datasets after
        cycling through all contained imputers. Not all returned datsets are
        saved unless specified in the iterator call.

        Returns
        -------

        data : pandas DataFrame
            Dataset with imputed values saved after invoking each Imputer
            object in imputer_list.
        """
        for im in self.imputer_list:
            im.impute_asymptotic_bayes()
        return self.data

class AnalysisChain(object):
    __doc__= """
    Fits the model of analytical interest to each dataset.
    Datasets to be used for analysis are chosen after an initial burnin period
    where no imputed data is used and also after skipping a set number of
    imputations for each iteration. Meant to be used as an iterator
    for the MICE class.

    Note: See mice.MICE and mice.MICE.combine
    """

    def __init__(self, imputer_chain, analysis_formula, analysis_class, skipnum,
                 burnin, save=False, init_args={}, fit_args={}):
        self.imputer_chain = imputer_chain
        self.analysis_formula = analysis_formula
        self.analysis_class = analysis_class
        self.init_args = init_args
        self.fit_args = fit_args
        self.skipnum = skipnum
        self.burnin = burnin
        self.burned = True
        self.save = save
        self.iter = 0

    def __iter__(self):
        return self

    def next(self):
        """
        Makes this class an iterator that returns the fitted analysis model.
        Handles skipping of imputation iterations, burnin period of
        unconsidered imputation iterations, and whether or not to save the
        datasets to which an analysis model is fit.

        Returns
        -------

        mdf : statsmodels fitted model
            Fitted model of interest on imputed dataset that has passed all
            skip and burnin criteria
        """
        scount = 0
        while scount < self.skipnum:
            if self.burned:
                for b in range(self.burnin):
                    self.imputer_chain.next()
                self.burned = False
            else:
                scount += 1
                if scount == self.skipnum:
                    data = self.imputer_chain.next()
                else:
                    self.imputer_chain.next()
            print scount
        md = self.analysis_class.from_formula(self.analysis_formula, data, **self.init_args)
        mdf = md.fit(**self.fit_args)
        if self.save:
            fname = "%s_%d.csv" % ('mice_', self.iter)
            data.to_csv(fname, index=False)
            self.iter += 1
        return mdf

    # Impute data sets and save them to disk, keep this around for now
#    def generate_data(self, num, skip, base_name):
#        for k in range(num):
#            for j in range(skip):
#                self.next()
#            fname = "%s_%d.csv" % (base_name, k)
#            self.imputer_list[0].data.data.to_csv(fname, index=False)
#            self.values.append(copy.deepcopy(self.imputer_list[self.implength - 1].data.values))
#            #self.imputer_list[0].data.mean_fill()

class MICE(object):
    __doc__= """
    Fits the analysis model to each imputed dataset and combines the
    results using Rubin's rule. Calls mice.Imputer_Chain and mice.AnalysisChain
    to handle imputation and fitting of analysis models to the correct imputed
    datasets, respectively.

    %(params)s

    analysis_formula : string
        Formula for model of interest to be fitted.
    analysis_class : statsmodels model
        Statsmodels model of interest.
    imputer_list : list
        List of Imputer objects, one for each variable to be imputed.
    %(extra_params)s

    **Attributes**

    data : pandas DataFrame
        Underlying data to be modified.

    Examples
    --------
    >>> import pandas as pd
    >>> import statsmodels.api as sm
    >>> from statsmodels.sandbox.mice import mice
    >>> data = pd.read_csv('directory_here')
    >>> impdata = mice.ImputedData(data)
    >>> m1 = impdata.new_imputer("x2")
    >>> m2 = impdata.new_imputer("x3")
    >>> m3 = impdata.new_imputer("x1", model_class=sm.Logit)
    >>> impcomb = mice.MICE("x1 ~ x2 + x3", sm.Logit, [m1,m2,m3])
    >>> p1 = impcomb.combine(20,10)

    p1 contains a sm.Logit instance with MICE-provided params and cov_params.

    """
    def __init__(self, analysis_formula, analysis_class, imputer_list,
                 init_args={}, fit_args={}):
        self.imputer_list = imputer_list
        self.analysis_formula = analysis_formula
        self.analysis_class = analysis_class
        self.init_args = init_args
        self.fit_args = fit_args

    def combine(self, iternum, skipnum, burnin=5, save=False):
        """
        Combines model results and returns the model of interest with
        pooled estimates/covariance matrix.

        Parameters
        ----------
        iternum : int
            Number of imputed datasets to fit.
        skipnum : int
            Number of imputed datasets to skip between imputed datasets that
            are used for analysis. This is done to give the conditional
            distribution time to settle down. The literature says that the
            MICE procedure converges in distribution fairly quickly;
            standard practice is to set this number to be around ten.
        burnin : int
            Number of iterations to throw away before ever starting the skipped
            datasets count.
        save : boolean
            Whether to save the imputed datasets chosen for analysis.

        Returns
        -------
        md : statsmodels fitted model
            Altered cov_params and params to be the MICE combined quantities.
        """
        imp_chain = ImputerChain(self.imputer_list)
        analysis_chain = AnalysisChain(imp_chain, self.analysis_formula, self.analysis_class, skipnum, burnin,
                                       save, self.init_args, self.fit_args)
        params_list = []
        cov_list = []
        scale_list = []
        current_iter = 0
        while current_iter < iternum:
            model = analysis_chain.next()
            params_list.append(model.params)
            cov_list.append(np.array(model.normalized_cov_params))
            scale_list.append(model.scale)
            current_iter += 1
            if current_iter == iternum:
                md = model
            print current_iter
        scale = np.mean(scale_list)
        params = np.mean(params_list, axis=0)
        within_g = np.mean(cov_list, axis=0)
        #Used MLE rather than method of moments between group covariance
        between_g = np.cov(np.array(params_list).T, bias=1)
        cov_params = within_g + (1 + 1/float(iternum)) * between_g
        md._results.params = params
        md._results.scale = scale
        md._results.normalized_cov_params = cov_params
        #Will have to modify more attributes of the model class returned
        return md

class MissingDataInfo(object):
    __doc__="""
    Contains all the missing data information from the passed-in data object.
    One for each column/variable!

    %(params)s

    data : pandas DataFrame with missing values.

    **Attributes**

    ix_miss : array
        Indices of missing values for a particular variable.
    ix_obs : array
        Indices of observed values for a particualr variable.
    """

    def __init__(self, data):
        null = pd.isnull(data)
        self.ix_miss = np.flatnonzero(null)
        self.ix_obs = np.flatnonzero(~null)
        if len(self.ix_obs) == 0:
            raise ValueError("Variable to be imputed has no observed values")