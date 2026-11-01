class EloDifficulty:
    """
    Système d'adaptation de la difficulté basé sur la méthode Elo (adaptée pour l'apprentissage cognitif).
    """
    def __init__(self, initial_level=5, k_factor=16, base_rating=1000):
        self.level = initial_level
        self.k_factor = k_factor
        self.rating = base_rating + (initial_level - 1) * 100
        self.history = []

    def expected_probability(self, user_rating, exercise_rating):
        """Calcule la probabilité de succès attendue selon la formule Elo standard."""
        return 1 / (1 + 10 ** ((exercise_rating - user_rating) / 400))

    def update(self, score):
        """
        Met à jour le niveau et le rating en fonction du score de l'exercice (0 à 100).
        - score >= 60 est considéré comme une réussite (1.0), sinon un échec (0.0).
        """
        if not (0 <= score <= 100):
            raise ValueError("Le score doit être compris entre 0 et 100.")

        actual_score = 1.0 if score >= 60 else 0.0
        exercise_rating = 1000 + (self.level - 1) * 100
        expected = self.expected_probability(self.rating, exercise_rating)
        
        # Mise à jour du score Elo du joueur/utilisateur
        self.rating += self.k_factor * (actual_score - expected)
        
        old_level = self.level
        calculated_level = round(1 + (self.rating - 1000) / 100)
        self.level = max(1, min(10, calculated_level))
        
        action = 'stable'
        if self.level > old_level:
            action = 'augmentation'
        elif self.level < old_level:
            action = 'diminution'

        result = {
            'old_level': old_level,
            'new_level': self.level,
            'action': action,
            'rating': round(self.rating, 2)
        }
        self.history.append(result)
        return result
