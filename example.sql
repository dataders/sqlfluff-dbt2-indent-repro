SELECT
    {% for column in ['a', 'b'] %}
    COALESCE(
        {% for value in [1, 2] %}
        {{ value }}{% if not loop.last %},{% endif %}
        {% endfor %}
    ) AS {{ column }}{% if not loop.last %},{% endif %}
    {% endfor %}
