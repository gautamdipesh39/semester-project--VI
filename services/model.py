"""A small, inspectable Bernoulli Naive Bayes implementation (no scikit-learn)."""
from collections import Counter, defaultdict
import math

class SymptomNaiveBayes:
    def __init__(self, alpha=1.0):
        self.alpha = alpha
        self.classes = []
        self.class_counts = Counter()
        self.feature_counts = defaultdict(Counter)
        self.features = set()
        self.total = 0

    def fit(self, samples):
        """samples is an iterable of (set_of_symptoms, disease)."""
        for symptoms, label in samples:
            symptoms = set(symptoms)
            self.class_counts[label] += 1
            self.total += 1
            self.features.update(symptoms)
            for symptom in symptoms:
                self.feature_counts[label][symptom] += 1
        self.classes = sorted(self.class_counts)
        return self

    def predict_proba(self, symptoms):
        symptoms = set(symptoms)
        if not self.total:
            return []
        scores = {}
        for label in self.classes:
            count = self.class_counts[label]
            score = math.log(count / self.total)
            for feature in self.features:
                p = (self.feature_counts[label][feature] + self.alpha) / (count + 2 * self.alpha)
                score += math.log(p if feature in symptoms else 1 - p)
            scores[label] = score
        highest = max(scores.values())
        weights = {name: math.exp(value - highest) for name, value in scores.items()}
        normalizer = sum(weights.values())
        return sorted(((name, value / normalizer) for name, value in weights.items()), key=lambda x: x[1], reverse=True)
