/**
 * i18n.js - Internationalization for Chelsea Voting Mini App
 * Supports Russian (ru, default) and English (en)
 */

var TRANSLATIONS = {
    ru: {
        // Tab labels
        tabs: {
            vote: 'Голосовать',
            history: 'История',
            profile: 'Профиль',
            settings: 'Настройки',
            admin: 'Админ',
            stats: 'Статистика'
        },

        // Vote tab
        vote: {
            loading: 'Загрузка...',
            no_active_polls: 'Нет активных голосований. Загляните позже!',
            current_match: 'Текущий матч',
            scale_info: 'Шкала: 0',
            players_count: 'игроков',
            starters: 'старт',
            subs: 'замен',
            starting_lineup: 'Стартовый состав',
            substitutes: 'Замены',
            starter_badge: 'СТАРТ',
            sub_badge: 'ЗАМЕНА',
            rate_players: 'Оцените игроков',
            submit: 'Отправить голос',
            already_voted: 'Вы уже проголосовали',
            sending: 'Отправка...',
            vote_accepted: 'Голос принят',
            all_ratings_unique: 'Все оценки должны быть уникальными!',
            rate_all_players: 'Оцените всех игроков! Осталось:',
            rated_of: 'Оценено',
            of: 'из',
            connection_error: 'Не удалось отправить. Проверьте соединение.',
            vote_success_toast: 'Голос успешно отправлен!',
            poll_created_toast: 'Голосование создано!'
        },

        // Countdown
        countdown: {
            time_remaining: 'Осталось времени для голосования',
            time_expired: 'Время вышло',
            voting_finished: 'Голосование завершено'
        },

        // History/Other tab
        history: {
            heading: 'История матчей',
            no_polls: 'Пока нет голосований.',
            status_open: 'Открыто',
            status_closed: 'Закрыто',
            total_voters: 'Всего голосов',
            max_label: 'Макс',
            view_results: 'Результаты'
        },

        // Profile tab
        profile: {
            heading: 'Мой профиль',
            loading: 'Загрузка...',
            votes_count: 'Голосов',
            avg_rating: 'Средняя оценка',
            custom_id: 'Ваш кастомный ID',
            custom_id_hint: 'У вас 10+ голосов - вы можете установить свой ID!',
            custom_id_label: 'Кастомный ID (уникальный)',
            custom_id_available: 'Кастомный ID доступен',
            save: 'Сохранить',
            enter_id: 'Введите ID',
            id_saved: 'ID сохранён!',
            id_copied: 'ID скопирован',
            badges: {
                veteran: 'Ветеран',
                active: 'Активный',
                seer: 'Провидец',
                rebel: 'Бунтарь',
                admin: 'Админ'
            }
        },

        // Settings tab
        settings: {
            heading: 'Настройки',
            language: 'Язык',
            theme: 'Тема',
            theme_dark: 'Тёмная',
            theme_light: 'Светлая',
            theme_stamford: 'Стэмфорд Бридж',
            theme_vintage: 'Винтаж',
            theme_stadium: 'Огни стадиона',
            theme_auto: 'Авто',
            notifications: 'Уведомления',
            notifications_label: 'Получать уведомления о новых голосованиях',
            background: 'Фон',
            background_label: 'Персональный фон (URL)',
            background_admin_hint: 'Админ может загрузить фон для всех на вкладке «Админ».',
            save: 'Сохранить фон',
            info: 'Информация',
            voting_period: 'Период голосования',
            hours: 'часов',
            max_rating: 'Макс. оценка'
        },

        // Admin tab
        admin: {
            heading: 'Админ-панель',
            access_denied: 'Доступ запрещён',
            loading: 'Загрузка...',
            config: {
                heading: 'Общие настройки (для всех)',
                max_scale: 'Макс. шкала',
                bot_name: 'Название бота',
                global_bg: 'Глобальный фон (URL)',
                save: 'Сохранить конфигурацию'
            },
            automation: {
                heading: 'Автоматизация',
                auto_create: 'Авто-создание голосований',
                auto_close: 'Авто-закрытие голосований',
                voting_period: 'Период голосования (часы)',
                notifications: 'Уведомления в чат',
                chat_id: 'Chat ID для уведомлений'
            },
            polls: {
                heading: 'Управление голосованиями',
                match_id: 'Match ID',
                title: 'Название',
                create: 'Создать голосование',
                close: 'Закрыть',
                closed: 'Закрыт',
                all_polls: 'Все голосования:',
                no_polls: 'Нет голосований.',
                close_confirm: 'Закрыть голосование?',
                poll_closed_toast: 'Голосование закрыто',
                poll_created_toast: 'Голосование создано!'
            },
            admins: {
                heading: 'Администраторы',
                new_user_id: 'User ID нового админа',
                username: 'Username (optional)',
                add: 'Добавить админа',
                current: 'Текущие админы:',
                none: 'Нет.',
                remove: 'Удалить',
                remove_confirm: 'Удалить права администратора?',
                added_toast: 'Админ добавлен!',
                removed_toast: 'Админ удалён',
                enter_id: 'Введите User ID'
            },
            vote_adjust: {
                heading: 'Корректировка голосов',
                poll_id: 'Poll ID',
                user_id: 'User ID',
                player_id: 'Player ID',
                new_rating: 'Новая оценка',
                apply: 'Применить корректировку',
                note: 'Все корректировки логируются.',
                applied_toast: 'Корректировка применена',
                fill_all: 'Заполните все поля'
            },
            backgrounds: {
                heading: 'Фоны (для всех)',
                label: 'Название',
                url: 'URL изображения',
                make_default: 'Сделать фоном по умолчанию',
                add: 'Добавить фон',
                available: 'Доступные фоны:',
                none: 'Нет фонов.',
                added_toast: 'Фон добавлен!',
                enter_url: 'Введите URL'
            },
            logs: {
                heading: 'Журнал действий',
                empty: 'Пусто.',
                admin_label: 'Админ',
                target_label: 'цель'
            },
            config_saved_toast: 'Конфигурация сохранена!',
            channel: {
                heading: 'Канал / Авто-публикация',
                chat_id: 'Chat ID канала для результатов',
                template: 'Шаблон результатов',
                announce: 'Анонсировать новые голосования',
                save: 'Сохранить настройки канала',
                top3: 'Топ-3',
                top5: 'Топ-5',
                full: 'Полный список',
                saved: 'Настройки канала сохранены!'
            },
            votes_view: {
                heading: 'Просмотр голосов',
                poll_id: 'Poll ID',
                load: 'Показать голоса',
                total_voters: 'Проголосовавших',
                total_votes: 'Голосов всего',
                empty: 'В этом опросе пока нет голосов.',
                enter_poll_id: 'Введите Poll ID'
            },
            reset_vote: {
                heading: 'Сбросить голос пользователя',
                note: 'Удалит голоса юзера в опросе и позволит проголосовать заново. Действие логируется как «reset_vote».',
                apply: 'Сбросить голос',
                confirm: 'Сбросить голос пользователя',
                applied_toast: 'Голос сброшен'
            },
            remove_votes: {
                heading: 'Удалить все голоса юзера в опросе',
                note: 'Жёсткое удаление голосов юзера в опросе. Логируется как «remove_votes» (для аудита).',
                apply: 'Удалить голоса',
                confirm: 'Удалить ВСЕ голоса пользователя',
                applied_toast: 'Голоса удалены'
            },
            challenges: {
                heading: 'Челленджи',
                note: 'После создания получишь ID — используй его для активации/деактивации.',
                title_field: 'Название',
                title_placeholder: 'Угадай топ-3 матча',
                title_required: 'Введите название',
                description: 'Описание',
                description_placeholder: 'Краткое описание',
                type: 'Тип',
                target: 'Цель (число)',
                reward_xp: 'Награда (XP)',
                end_time: 'End time (unix, опц.)',
                end_time_placeholder: 'по умолчанию +7 дней',
                create: 'Создать челлендж',
                created_toast: 'Челлендж создан, ID:',
                toggle_heading: 'Активация / деактивация',
                challenge_id: 'Challenge ID',
                id_required: 'Введите Challenge ID',
                activate: 'Активировать',
                deactivate: 'Деактивировать',
                activated_toast: 'Челлендж активирован',
                deactivated_toast: 'Челлендж деактивирован'
            }
        },

        // Monitoring
        monitoring: {
            title: 'Мониторинг',
            last_run: 'Последний запуск',
            errors: 'Ошибки API',
            status: 'Статус',
            status_ok: 'OK',
            status_warning: 'Внимание',
            reset_errors: 'Сбросить счётчик ошибок',
            users: 'Пользователи',
            votes: 'Голоса',
            polls: 'Голосования'
        },

        // Stats tab
        stats: {
            season_stats: 'Статистика сезона',
            team_of_season: 'Команда сезона',
            player_form: 'Форма игрока',
            leaderboard: 'Таблица лидеров'
        },

        // Predictions
        predictions: {
            predict_best: 'Кто будет лучшим игроком?',
            your_prediction: 'Ваш прогноз',
            results: 'Результаты прогнозов',
            points: 'Очки',
            submit: 'Отправить прогноз',
            select_player: 'Выберите игрока',
            submitted: 'Прогноз отправлен!',
            leaderboard: 'Таблица прогнозов'
        },

        // Mini-games
        games: {
            heading: 'Мини-игры',
            guess_lineup: 'Угадай состав',
            guess_score: 'Угадай счёт',
            results: 'Результаты',
            home: 'Хозяева',
            away: 'Гости',
            submit_score: 'Отправить прогноз счёта',
            submit_lineup: 'Отправить состав',
            selected_count: 'Выбрано',
            of_eleven: 'из 11',
            score_submitted: 'Прогноз счёта отправлен!',
            lineup_submitted: 'Прогноз состава отправлен!',
            select_exactly_11: 'Выберите ровно 11 игроков',
            already_submitted: 'Уже отправлено',
            your_guess: 'Ваш прогноз',
            points_earned: 'Очков заработано'
        },

        // Social
        social: {
            share: 'Поделиться',
            compare: 'Сравнить с другом',
            compare_heading: 'Сравнение с другом',
            friend_id: 'User ID друга',
            compare_btn: 'Сравнить',
            similarity: 'Совпадение',
            common_polls: 'Общих голосований',
            referral: 'Реферальная программа',
            referral_code: 'Ваш реферальный код',
            copy_link: 'Копировать ссылку',
            copied: 'Скопировано в буфер!',
            referral_text: 'Присоединяйся к Chelsea Voting! Мой код:',
            referrals_count: 'Приглашённых друзей',
            share_results: 'Поделиться результатами',
            top_5: 'Топ 5'
        },

        // Notifications
        notifications: {
            reminder: 'Напоминание',
            new_poll: 'Новое голосование',
            results_ready: 'Результаты готовы',
            prefs_title: 'Уведомления',
            remind_before_close: 'Напомнить за 2 часа до закрытия',
            results_notify: 'Уведомить о результатах'
        },

        // Customization
        customization: {
            sound_effects: 'Звуковые эффекты',
            sound_on: 'Звук включён',
            sound_off: 'Звук выключен',
            avatar: 'Аватар',
            choose_avatar: 'Выберите аватар',
            confetti: 'Конфетти'
        },

        // Common
        common: {
            loading: 'Загрузка...',
            error: 'Ошибка',
            success: 'Успех',
            save: 'Сохранить',
            cancel: 'Отмена',
            close: 'Закрыть',
            confirm: 'Подтвердить'
        },

        // Toast messages
        toast: {
            saved: 'Сохранено',
            error_saving: 'Ошибка сохранения',
            vote_submitted: 'Голос успешно отправлен!',
            poll_created: 'Голосование создано!',
            error_creating_poll: 'Ошибка создания голосования'
        },

        // Medals
        medals: {
            gold: 'Золото',
            silver: 'Серебро',
            bronze: 'Бронза'
        },

        // Re-vote
        revote: {
            change_vote: 'Изменить голос',
            available: 'Переголосование доступно',
            time_to_revote: 'Время для переголосования',
            hours_remaining: 'Осталось часов для изменения голоса',
            vote_reset: 'Голос сброшен. Вы можете проголосовать снова.'
        },

        // XP system
        xp: {
            level: 'Уровень',
            total_xp: 'Всего XP',
            next_level: 'До следующего уровня',
            progress: 'Прогресс',
            streak_current: 'Текущая серия',
            streak_record: 'Рекорд серии',
            fire_streak: 'Огненная серия!',
            locked: 'Заблокировано',
            unlock_at: 'Доступно на уровне'
        },
        levels: {
            novice: 'Новичок',
            fan: 'Фанат',
            ultras: 'Ультрас',
            legend: 'Легенда Стэмфорд Бридж'
        },

        // Events
        events: {
            goal: 'Гол',
            yellow_card: 'ЖК',
            red_card: 'КК',
            substitution: 'Замена',
            sub_out: 'Ушёл',
            sub_in: 'Вышел'
        },
        timeline: {
            title: 'Хронология матча',
            show: 'Показать',
            hide: 'Скрыть',
            minute: 'мин'
        },
        ai_rating: {
            title: 'Мнение бота',
            bot_thinks: 'Бот считает',
            you: 'Вы',
            bot: 'Бот',
            community: 'Среднее',
            comparison: 'Сравнение оценок'
        },

        // Heatmap
        heatmap: {
            title: 'Тепловая карта голосов',
            your_patterns: 'Ваши паттерны',
            high_rater: 'Высоко оцениваете',
            low_rater: 'Низко оцениваете',
            neutral: 'Нейтрально',
            no_data: 'Недостаточно данных для анализа'
        },
        controversial: {
            title: 'Самый спорный игрок',
            most_controversial: 'Самый спорный',
            std_dev: 'Разброс оценок',
            badge_text: 'Спорный',
            high_variance: 'Мнения разделились!'
        },

        overrated: {
            title: 'Переоценённые / Недооценённые',
            overrated_by_fans: 'Фанаты ставят выше',
            underrated_by_fans: 'Фанаты ставят ниже',
            fair: 'Справедливая оценка',
            vs_ai: 'vs AI рейтинг',
            no_data: 'Нет данных AI для анализа'
        },

        // Share card
        share: {
            generate_card: 'Создать карточку',
            share_card: 'Поделиться карточкой',
            downloading: 'Генерация...',
            card_ready: 'Карточка готова!'
        },
        live: {
            voters_now: 'уже проголосовали',
            just_voted: 'только что проголосовал(а)!',
            connected: 'Онлайн',
            watching: 'следят за голосованием'
        },

        // Demo
        demo: {
            banner: 'ДЕМО-РЕЖИМ',
            switch_user: 'на User ID:'
        },

        // Challenges
        challenges: {
            title: 'Испытания',
            active: 'Активные',
            completed: 'Выполнено',
            reward: 'Награда',
            progress: 'Прогресс',
            time_remaining: 'Осталось',
            no_active: 'Нет активных испытаний',
            daily: 'Ежедневное',
            weekly: 'Еженедельное'
        },

        // Awards
        awards: {
            title: 'Награды',
            most_accurate: 'Самый точный',
            most_active: 'Самый активный',
            best_predictor: 'Лучший предсказатель',
            streak_record: 'Рекорд серии',
            month_label: 'Месяц',
            no_awards: 'Пока нет наград',
            earned: 'Получено'
        },

        // FPL
        fpl: {
            title: 'Очки FPL',
            gameweek: 'Тур',
            points: 'очк.',
            correlation: 'Корреляция рейтинг-FPL',
            no_data: 'Данные FPL недоступны',
            high_correlation: 'Сильная корреляция',
            low_correlation: 'Слабая корреляция'
        },

        // Analytics
        analytics: {
            title: 'Предматчевая аналитика',
            opponent_form: 'Форма соперника',
            h2h: 'Личные встречи',
            prediction: 'Прогноз',
            wins: 'П',
            draws: 'Н',
            losses: 'П(о)',
            no_data: 'Нет данных',
            last_meetings: 'Последние встречи'
        },

        // Report
        report: {
            title: 'Отчёт о матче',
            fan_mvp: 'MVP фанатов',
            top_3: 'Топ 3',
            controversial: 'Самый спорный',
            voters: 'Всего голосов',
            ai_comparison: 'AI vs Фанаты',
            no_report: 'Отчёт недоступен',
            view_report: 'Показать отчёт'
        }
    },

    en: {
        // Tab labels
        tabs: {
            vote: 'Vote',
            history: 'History',
            profile: 'Profile',
            settings: 'Settings',
            admin: 'Admin',
            stats: 'Stats'
        },

        // Vote tab
        vote: {
            loading: 'Loading...',
            no_active_polls: 'No active polls. Check back later!',
            current_match: 'Current match',
            scale_info: 'Scale: 0',
            players_count: 'players',
            starters: 'starters',
            subs: 'subs',
            starting_lineup: 'Starting Lineup',
            substitutes: 'Substitutes',
            starter_badge: 'START',
            sub_badge: 'SUB',
            rate_players: 'Rate players',
            submit: 'Submit vote',
            already_voted: 'You already voted',
            sending: 'Sending...',
            vote_accepted: 'Vote accepted',
            all_ratings_unique: 'All ratings must be unique!',
            rate_all_players: 'Rate all players! Remaining:',
            rated_of: 'Rated',
            of: 'of',
            connection_error: 'Failed to send. Check your connection.',
            vote_success_toast: 'Vote submitted successfully!',
            poll_created_toast: 'Poll created!'
        },

        // Countdown
        countdown: {
            time_remaining: 'Time remaining to vote',
            time_expired: 'Time expired',
            voting_finished: 'Voting finished'
        },

        // History/Other tab
        history: {
            heading: 'Match History',
            no_polls: 'No polls yet.',
            status_open: 'Open',
            status_closed: 'Closed',
            total_voters: 'Total votes',
            max_label: 'Max',
            view_results: 'Results'
        },

        // Profile tab
        profile: {
            heading: 'My Profile',
            loading: 'Loading...',
            votes_count: 'Votes',
            avg_rating: 'Avg rating',
            custom_id: 'Your custom ID',
            custom_id_hint: 'You have 10+ votes - you can set your own ID!',
            custom_id_label: 'Custom ID (unique)',
            custom_id_available: 'Custom ID available',
            save: 'Save',
            enter_id: 'Enter ID',
            id_saved: 'ID saved!',
            id_copied: 'ID copied',
            badges: {
                veteran: 'Veteran',
                active: 'Active',
                seer: 'Seer',
                rebel: 'Rebel',
                admin: 'Admin'
            }
        },

        // Settings tab
        settings: {
            heading: 'Settings',
            language: 'Language',
            theme: 'Theme',
            theme_dark: 'Dark',
            theme_light: 'Light',
            theme_stamford: 'Stamford Bridge',
            theme_vintage: 'Vintage',
            theme_stadium: 'Stadium Lights',
            theme_auto: 'Auto',
            notifications: 'Notifications',
            notifications_label: 'Receive notifications about new polls',
            background: 'Background',
            background_label: 'Personal background (URL)',
            background_admin_hint: 'Admin can upload a background for everyone in the Admin tab.',
            save: 'Save background',
            info: 'Info',
            voting_period: 'Voting period',
            hours: 'hours',
            max_rating: 'Max rating'
        },

        // Admin tab
        admin: {
            heading: 'Admin Panel',
            access_denied: 'Access denied',
            loading: 'Loading...',
            config: {
                heading: 'General Settings (for all)',
                max_scale: 'Max scale',
                bot_name: 'Bot name',
                global_bg: 'Global background (URL)',
                save: 'Save configuration'
            },
            automation: {
                heading: 'Automation',
                auto_create: 'Auto-create polls',
                auto_close: 'Auto-close polls',
                voting_period: 'Voting period (hours)',
                notifications: 'Chat notifications',
                chat_id: 'Chat ID for notifications'
            },
            polls: {
                heading: 'Poll Management',
                match_id: 'Match ID',
                title: 'Title',
                create: 'Create poll',
                close: 'Close',
                closed: 'Closed',
                all_polls: 'All polls:',
                no_polls: 'No polls.',
                close_confirm: 'Close this poll?',
                poll_closed_toast: 'Poll closed',
                poll_created_toast: 'Poll created!'
            },
            admins: {
                heading: 'Administrators',
                new_user_id: 'New admin User ID',
                username: 'Username (optional)',
                add: 'Add admin',
                current: 'Current admins:',
                none: 'None.',
                remove: 'Remove',
                remove_confirm: 'Remove admin rights?',
                added_toast: 'Admin added!',
                removed_toast: 'Admin removed',
                enter_id: 'Enter User ID'
            },
            vote_adjust: {
                heading: 'Vote Adjustment',
                poll_id: 'Poll ID',
                user_id: 'User ID',
                player_id: 'Player ID',
                new_rating: 'New rating',
                apply: 'Apply adjustment',
                note: 'All adjustments are logged.',
                applied_toast: 'Adjustment applied',
                fill_all: 'Fill in all fields'
            },
            backgrounds: {
                heading: 'Backgrounds (for all)',
                label: 'Label',
                url: 'Image URL',
                make_default: 'Set as default background',
                add: 'Add background',
                available: 'Available backgrounds:',
                none: 'No backgrounds.',
                added_toast: 'Background added!',
                enter_url: 'Enter URL'
            },
            logs: {
                heading: 'Action Log',
                empty: 'Empty.',
                admin_label: 'Admin',
                target_label: 'target'
            },
            config_saved_toast: 'Configuration saved!',
            channel: {
                heading: 'Channel / Auto-post',
                chat_id: 'Channel Chat ID for results',
                template: 'Results template',
                announce: 'Announce new polls',
                save: 'Save channel settings',
                top3: 'Top-3',
                top5: 'Top-5',
                full: 'Full list',
                saved: 'Channel settings saved!'
            },
            votes_view: {
                heading: 'View votes',
                poll_id: 'Poll ID',
                load: 'Load votes',
                total_voters: 'Total voters',
                total_votes: 'Total votes',
                empty: 'No votes in this poll yet.',
                enter_poll_id: 'Enter Poll ID'
            },
            reset_vote: {
                heading: "Reset user's vote",
                note: "Removes the user's votes in the poll so they can vote again. Logged as \"reset_vote\".",
                apply: 'Reset vote',
                confirm: "Reset votes of user",
                applied_toast: 'Vote reset'
            },
            remove_votes: {
                heading: "Remove all of user's votes in poll",
                note: "Hard-removes the user's votes in the poll. Logged as \"remove_votes\" (audit trail).",
                apply: 'Remove votes',
                confirm: "Remove ALL votes of user",
                applied_toast: 'Votes removed'
            },
            challenges: {
                heading: 'Challenges',
                note: 'After creating you will get an ID — use it to toggle active state.',
                title_field: 'Title',
                title_placeholder: 'Guess match top-3',
                title_required: 'Title required',
                description: 'Description',
                description_placeholder: 'Short description',
                type: 'Type',
                target: 'Target (number)',
                reward_xp: 'Reward (XP)',
                end_time: 'End time (unix, optional)',
                end_time_placeholder: 'defaults to +7 days',
                create: 'Create challenge',
                created_toast: 'Challenge created, ID:',
                toggle_heading: 'Activate / deactivate',
                challenge_id: 'Challenge ID',
                id_required: 'Challenge ID required',
                activate: 'Activate',
                deactivate: 'Deactivate',
                activated_toast: 'Challenge activated',
                deactivated_toast: 'Challenge deactivated'
            }
        },

        // Monitoring
        monitoring: {
            title: 'Monitoring',
            last_run: 'Last Run',
            errors: 'API Errors',
            status: 'Status',
            status_ok: 'OK',
            status_warning: 'Warning',
            reset_errors: 'Reset Error Counter',
            users: 'Users',
            votes: 'Votes',
            polls: 'Polls'
        },

        // Stats tab
        stats: {
            season_stats: 'Season Stats',
            team_of_season: 'Team of the Season',
            player_form: 'Player Form',
            leaderboard: 'Leaderboard'
        },

        // Predictions
        predictions: {
            predict_best: 'Who will be the best player?',
            your_prediction: 'Your prediction',
            results: 'Prediction results',
            points: 'Points',
            submit: 'Submit Prediction',
            select_player: 'Select a player',
            submitted: 'Prediction submitted!',
            leaderboard: 'Prediction Leaderboard'
        },

        // Mini-games
        games: {
            heading: 'Mini Games',
            guess_lineup: 'Guess the lineup',
            guess_score: 'Guess the score',
            results: 'Results',
            home: 'Home',
            away: 'Away',
            submit_score: 'Submit Score Prediction',
            submit_lineup: 'Submit Lineup',
            selected_count: 'Selected',
            of_eleven: 'of 11',
            score_submitted: 'Score prediction submitted!',
            lineup_submitted: 'Lineup prediction submitted!',
            select_exactly_11: 'Select exactly 11 players',
            already_submitted: 'Already submitted',
            your_guess: 'Your guess',
            points_earned: 'Points earned'
        },

        // Social
        social: {
            share: 'Share',
            compare: 'Compare with friend',
            compare_heading: 'Compare with Friend',
            friend_id: 'Friend User ID',
            compare_btn: 'Compare',
            similarity: 'Similarity',
            common_polls: 'Common polls',
            referral: 'Referral Program',
            referral_code: 'Your referral code',
            copy_link: 'Copy link',
            copied: 'Copied to clipboard!',
            referral_text: 'Join Chelsea Voting! My code:',
            referrals_count: 'Friends referred',
            share_results: 'Share Results',
            top_5: 'Top 5'
        },

        // Notifications
        notifications: {
            reminder: 'Reminder',
            new_poll: 'New poll',
            results_ready: 'Results ready',
            prefs_title: 'Notifications',
            remind_before_close: 'Remind 2 hours before close',
            results_notify: 'Notify when results are ready'
        },

        // Customization
        customization: {
            sound_effects: 'Sound effects',
            sound_on: 'Sound on',
            sound_off: 'Sound off',
            avatar: 'Avatar',
            choose_avatar: 'Choose avatar',
            confetti: 'Confetti'
        },

        // Common
        common: {
            loading: 'Loading...',
            error: 'Error',
            success: 'Success',
            save: 'Save',
            cancel: 'Cancel',
            close: 'Close',
            confirm: 'Confirm'
        },

        // Toast messages
        toast: {
            saved: 'Saved',
            error_saving: 'Error saving',
            vote_submitted: 'Vote submitted successfully!',
            poll_created: 'Poll created!',
            error_creating_poll: 'Error creating poll'
        },

        // Medals
        medals: {
            gold: 'Gold',
            silver: 'Silver',
            bronze: 'Bronze'
        },

        // Re-vote
        revote: {
            change_vote: 'Change vote',
            available: 'Re-vote available',
            time_to_revote: 'Time to re-vote',
            hours_remaining: 'Hours remaining to change vote',
            vote_reset: 'Vote reset. You can vote again.'
        },

        // XP system
        xp: {
            level: 'Level',
            total_xp: 'Total XP',
            next_level: 'To next level',
            progress: 'Progress',
            streak_current: 'Current streak',
            streak_record: 'Streak record',
            fire_streak: 'Fire streak!',
            locked: 'Locked',
            unlock_at: 'Unlocks at level'
        },
        levels: {
            novice: 'Novice',
            fan: 'Fan',
            ultras: 'Ultras',
            legend: 'Stamford Bridge Legend'
        },

        // Events
        events: {
            goal: 'Goal',
            yellow_card: 'YC',
            red_card: 'RC',
            substitution: 'Sub',
            sub_out: 'Off',
            sub_in: 'On'
        },
        timeline: {
            title: 'Match Timeline',
            show: 'Show',
            hide: 'Hide',
            minute: 'min'
        },
        ai_rating: {
            title: "Bot's Opinion",
            bot_thinks: 'Bot thinks',
            you: 'You',
            bot: 'Bot',
            community: 'Average',
            comparison: 'Rating Comparison'
        },

        // Heatmap
        heatmap: {
            title: 'Vote Heatmap',
            your_patterns: 'Your Patterns',
            high_rater: 'You rate high',
            low_rater: 'You rate low',
            neutral: 'Neutral',
            no_data: 'Not enough data for analysis'
        },
        controversial: {
            title: 'Most Controversial Player',
            most_controversial: 'Most Controversial',
            std_dev: 'Rating spread',
            badge_text: 'Controversial',
            high_variance: 'Opinions divided!'
        },

        overrated: {
            title: 'Overrated / Underrated',
            overrated_by_fans: 'Fans rate higher',
            underrated_by_fans: 'Fans rate lower',
            fair: 'Fair rating',
            vs_ai: 'vs AI rating',
            no_data: 'No AI data available'
        },

        // Share card
        share: {
            generate_card: 'Generate Card',
            share_card: 'Share Card',
            downloading: 'Generating...',
            card_ready: 'Card ready!'
        },
        live: {
            voters_now: 'voted already',
            just_voted: 'just voted!',
            connected: 'Live',
            watching: 'watching the poll'
        },

        // Demo
        demo: {
            banner: 'DEMO MODE',
            switch_user: 'to User ID:'
        },

        // Challenges
        challenges: {
            title: 'Challenges',
            active: 'Active',
            completed: 'Completed',
            reward: 'Reward',
            progress: 'Progress',
            time_remaining: 'Time left',
            no_active: 'No active challenges',
            daily: 'Daily',
            weekly: 'Weekly'
        },

        // Awards
        awards: {
            title: 'Awards',
            most_accurate: 'Most Accurate',
            most_active: 'Most Active',
            best_predictor: 'Best Predictor',
            streak_record: 'Streak Record',
            month_label: 'Month',
            no_awards: 'No awards yet',
            earned: 'Earned'
        },

        // FPL
        fpl: {
            title: 'FPL Points',
            gameweek: 'Gameweek',
            points: 'pts',
            correlation: 'Rating-FPL Correlation',
            no_data: 'FPL data not available',
            high_correlation: 'Strong correlation',
            low_correlation: 'Weak correlation'
        },

        // Analytics
        analytics: {
            title: 'Pre-match Analytics',
            opponent_form: 'Opponent Form',
            h2h: 'Head to Head',
            prediction: 'Predicted Result',
            wins: 'W',
            draws: 'D',
            losses: 'L',
            no_data: 'No data available',
            last_meetings: 'Last meetings'
        },

        // Report
        report: {
            title: 'Match Report',
            fan_mvp: 'Fan MVP',
            top_3: 'Top 3',
            controversial: 'Most Controversial',
            voters: 'Total Voters',
            ai_comparison: 'AI Comparison',
            no_report: 'Report not available',
            view_report: 'View Report'
        }
    }
};

/**
 * Get current language from localStorage, default 'ru'
 */
function getLang() {
    try {
        return localStorage.getItem('chelsea_lang') || 'ru';
    } catch (e) {
        return 'ru';
    }
}

/**
 * Set language, save to localStorage, and update the page
 */
function setLang(lang) {
    if (lang !== 'ru' && lang !== 'en') lang = 'ru';
    try {
        localStorage.setItem('chelsea_lang', lang);
    } catch (e) { /* ignore */ }
    updateTabLabels();
    // Re-render the current tab
    var currentTab = location.hash.replace('#', '') || 'vote';
    switchTab(currentTab);
}

/**
 * Translate a key using dot notation, e.g. t('vote.submit')
 * Returns the translated string for the current language, or the key itself if not found.
 */
function t(key) {
    var lang = getLang();
    var obj = TRANSLATIONS[lang] || TRANSLATIONS['ru'];
    var parts = key.split('.');
    var result = obj;
    for (var i = 0; i < parts.length; i++) {
        if (result && typeof result === 'object' && parts[i] in result) {
            result = result[parts[i]];
        } else {
            return key;
        }
    }
    return (typeof result === 'string') ? result : key;
}

/**
 * Update tab labels to reflect current language
 */
function updateTabLabels() {
    var tabs = document.querySelectorAll('.tab-btn');
    tabs.forEach(function(btn) {
        var tab = btn.dataset.tab;
        var labelEl = btn.querySelector('.tab-label');
        if (!labelEl) return;
        if (tab === 'vote') labelEl.textContent = t('tabs.vote');
        else if (tab === 'other') labelEl.textContent = t('tabs.history');
        else if (tab === 'profile') labelEl.textContent = t('tabs.profile');
        else if (tab === 'settings') labelEl.textContent = t('tabs.settings');
        else if (tab === 'admin') labelEl.textContent = t('tabs.admin');
        else if (tab === 'stats') labelEl.textContent = t('tabs.stats');
    });
}
