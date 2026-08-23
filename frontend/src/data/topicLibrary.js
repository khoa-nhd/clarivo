export const topicLibrary = [
  {
    id: 'merge-sort',
    title: 'Explain Merge Sort',
    domain: 'Data Structures & Algorithms',
    difficulty: 'Medium',
    recommendedAudience: 'Intermediate',
    taskDescription: 'Explain the divide-and-conquer idea, how the merge step works, the time complexity, memory trade-off, and one useful property or application.',
    preStudyKeywords: ['Divide and Conquer', 'Merge step', 'O(n log n)', 'Auxiliary memory', 'Stable sort'],
    referenceContent: `Merge Sort is a divide-and-conquer sorting algorithm. It recursively divides the input into smaller halves until subarrays contain one element, then merges sorted subarrays by repeatedly taking the smaller front element. Its time complexity is O(n log n) in the best, average, and worst cases. A typical array implementation uses O(n) auxiliary memory during merging. Merge Sort is stable when equal elements preserve their relative order. It is useful when predictable O(n log n) performance and stability matter, and external merge sort is important when data does not fit in memory.`,
  },
  {
    id: 'least-squares',
    title: 'Why Least Squares Uses Squared Errors',
    domain: 'Machine Learning',
    difficulty: 'Hard',
    recommendedAudience: 'Advanced',
    taskDescription: 'Explain residuals, why errors are squared, what objective is minimized, how the optimum is found, and one assumption or limitation.',
    preStudyKeywords: ['Residual', 'Squared error', 'Convex objective', 'Gradient', 'Normal equation'],
    referenceContent: `Ordinary least squares chooses parameters that minimize the sum of squared residuals between observed and predicted values. Squaring prevents positive and negative residuals from cancelling, penalizes large errors more strongly, and produces a smooth convex quadratic objective for linear regression. Setting the gradient of that objective to zero yields the normal equations. If the design matrix has full column rank the solution is unique; otherwise a pseudoinverse can be used. Gaussian noise is not required to compute the OLS estimator, although it is commonly used for probabilistic interpretation and inference.`,
  },
  {
    id: 'photosynthesis',
    title: 'Explain Photosynthesis',
    domain: 'Biology',
    difficulty: 'Easy',
    recommendedAudience: 'Beginner',
    taskDescription: 'Explain what photosynthesis does, the main inputs and outputs, where it happens, and why light energy matters.',
    preStudyKeywords: ['Chloroplast', 'Chlorophyll', 'Carbon dioxide', 'Water', 'Glucose'],
    referenceContent: `Photosynthesis is the process by which plants, algae, and some microorganisms convert light energy into chemical energy. In plants it occurs mainly in chloroplasts. Carbon dioxide and water are used to produce carbohydrates such as glucose, while oxygen is released. Chlorophyll and other pigments absorb light. The light-dependent reactions capture energy and generate energy-carrying molecules, while the Calvin cycle uses carbon dioxide to build sugars.`,
  },
  {
    id: 'p-value',
    title: 'Explain the Meaning of a P-value',
    domain: 'Statistics',
    difficulty: 'Medium',
    recommendedAudience: 'Intermediate',
    taskDescription: 'Define a p-value correctly, explain what a small p-value means under the null hypothesis, and distinguish it from the probability that the null hypothesis is true.',
    preStudyKeywords: ['Null hypothesis', 'Test statistic', 'Extreme result', 'Significance level', 'Type I error'],
    referenceContent: `A p-value is the probability, assuming the null hypothesis and the statistical model are true, of observing a test statistic at least as extreme as the one observed. A small p-value indicates that the observed data would be relatively unusual under the null hypothesis. It is not the probability that the null hypothesis is true, and it is not by itself a measure of effect size or practical importance. A chosen significance level such as 0.05 is a decision threshold, not a universal law.`,
  },
  {
    id: 'decision-tree',
    title: 'Explain Decision Trees',
    domain: 'Machine Learning',
    difficulty: 'Medium',
    recommendedAudience: 'Intermediate',
    taskDescription: 'Explain how a decision tree splits data, how a split is selected, why trees can overfit, and how depth/pruning controls complexity.',
    preStudyKeywords: ['Node split', 'Entropy', 'Gini impurity', 'Overfitting', 'Pruning'],
    referenceContent: `A decision tree recursively partitions the feature space using feature-based rules. Classification trees commonly choose splits that reduce impurity, measured with criteria such as Gini impurity or entropy. Trees are easy to interpret and can model nonlinear interactions, but deep trees can overfit training data and be unstable to small data changes. Maximum depth, minimum sample rules, pruning, and ensembles such as random forests are common ways to control or reduce these weaknesses.`,
  },
]

export function randomTopic(topics = topicLibrary) {
  const pool = Array.isArray(topics) && topics.length ? topics : topicLibrary
  return pool[Math.floor(Math.random() * pool.length)]
}
